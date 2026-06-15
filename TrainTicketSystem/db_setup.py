"""
db_setup.py  (V3.0 动态计价引擎)

数据库预置脚本 — 固定测试集，一键就绪。

特性：
- 创建全部 7 张表 + 1 个财务视图（幂等）
- 包含 train_models（车型费率）与 seat_classes（席别倍率）字典表
- 事务内批量写入：G101 车次 + 3 种车型 + 3 种席别 + 4 经停站 + 25 个分级座位 + 2 个用户
- 座位分级：第1排 SWZ(商务3.0×) | 第2排 YDZ(一等1.6×) | 3-5排 EDZ(二等1.0×)
- 支持 --reset 一键 DROP 重建

用法：
    python db_setup.py              # 幂等初始化（已有数据则跳过）
    python db_setup.py --reset      # 强制重建（DROP + CREATE + INSERT）
"""
import argparse
import hashlib
import secrets

from utils.db_helper import get_connection


# =========================================================================
# 建表 DDL（与 sql_scripts/01_init_db.sql 完全一致）
# =========================================================================

def ensure_tables():
    """创建全部 5 张表（幂等）。"""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            # ---- train_models（V3.0 动态计价：车型基准费率） ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS train_models (
                    type_code   VARCHAR(10)   PRIMARY KEY   COMMENT '车型代码，如 G/D/K',
                    type_name   VARCHAR(50)   NOT NULL      COMMENT '车型名称，如 高铁/动车/普快',
                    base_rate   DECIMAL(10,2) NOT NULL      COMMENT '基准费率（元/站）'
                ) ENGINE=InnoDB COMMENT='车型基准费率表（动态计价引擎核心）';
            ''')

            # ---- seat_classes（V3.0 动态计价：座位等级倍率） ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS seat_classes (
                    class_code       VARCHAR(10)   PRIMARY KEY   COMMENT '席别代码，如 SWZ/YDZ/EDZ',
                    class_name       VARCHAR(50)   NOT NULL      COMMENT '席别名称，如 商务座/一等座/二等座',
                    price_multiplier DECIMAL(4,2)  NOT NULL      COMMENT '价格倍率'
                ) ENGINE=InnoDB COMMENT='座位等级倍率表（动态计价引擎核心）';
            ''')

            # ---- train_info ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS train_info (
                    train_id       VARCHAR(20)   PRIMARY KEY   COMMENT '车次编号，如 G101',
                    train_no       VARCHAR(20)                 COMMENT '车次号',
                    departure      VARCHAR(100)  NOT NULL      COMMENT '始发站',
                    arrival        VARCHAR(100)  NOT NULL      COMMENT '终点站',
                    total_seats    INT           NOT NULL      COMMENT '总座位数',
                    departure_time DATETIME      NOT NULL      COMMENT '发车时间',
                    price          DECIMAL(10,2)               COMMENT '票价（元）'
                ) ENGINE=InnoDB COMMENT='列车基础信息表';
            ''')

            # ---- seat_status ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS seat_status (
                    seat_id       INT AUTO_INCREMENT PRIMARY KEY  COMMENT '座位全局唯一 ID',
                    train_id      VARCHAR(20)  NOT NULL           COMMENT '所属车次编号',
                    carriage_no   INT          NOT NULL           COMMENT '车厢号',
                    seat_no       VARCHAR(10)  NOT NULL           COMMENT '座位号，如 01A',
                    class_code    VARCHAR(10)  DEFAULT 'EDZ'      COMMENT '席别代码 → seat_classes.class_code',
                    seat_bitmap   INT          DEFAULT 0          COMMENT '二进制区间占用状态：0=全空闲',
                    default_mask  INT          DEFAULT 0          COMMENT '该座位的默认区间掩码',
                    UNIQUE KEY uk_train_seat (train_id, carriage_no, seat_no)
                ) ENGINE=InnoDB COMMENT='高并发座位区间状态表（位图模型核心）';
            ''')
            # V3.0 兼容旧表：若 seat_status 已存在但缺少 class_code 列，自动补齐
            try:
                cursor.execute(
                    """ALTER TABLE seat_status
                       ADD COLUMN class_code VARCHAR(10) DEFAULT 'EDZ'
                       COMMENT '席别代码 → seat_classes.class_code'"""
                )
            except Exception:
                pass  # 列已存在则忽略

            # ---- orders ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    order_id     VARCHAR(64)   PRIMARY KEY            COMMENT '订单流水号',
                    user_id      VARCHAR(64)   NOT NULL               COMMENT '购票用户 ID',
                    train_id     VARCHAR(20)                          COMMENT '车次编号',
                    seat_id      INT                                  COMMENT '关联 seat_status.seat_id',
                    buy_mask     INT           DEFAULT 0              COMMENT '本次购买的区间掩码',
                    price        DECIMAL(10,2) DEFAULT 0              COMMENT '订单金额',
                    order_status VARCHAR(20)   DEFAULT 'PAID'         COMMENT '字符串状态：PAID / REFUNDED',
                    status       INT           DEFAULT 1              COMMENT '数值状态：1=已支付, 2=已退票',
                    create_time  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP COMMENT '订单创建时间'
                ) ENGINE=InnoDB COMMENT='交易订单表';
            ''')

            # ---- train_stops ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS train_stops (
                    id              INT AUTO_INCREMENT PRIMARY KEY   COMMENT '主键',
                    train_id        VARCHAR(20) NOT NULL             COMMENT '关联车次编号',
                    station_name    VARCHAR(100) NOT NULL            COMMENT '车站名称',
                    stop_index      INT NOT NULL                     COMMENT '经停序号（从0开始），直接对应位图偏移量',
                    arrival_time    DATETIME                         COMMENT '到站时间（首站可为NULL）',
                    departure_time  DATETIME                         COMMENT '离站时间（末站可为NULL）',
                    UNIQUE KEY uk_train_stop (train_id, stop_index),
                    UNIQUE KEY uk_train_station (train_id, station_name),
                    CONSTRAINT fk_stops_train
                        FOREIGN KEY (train_id) REFERENCES train_info(train_id)
                        ON DELETE CASCADE ON UPDATE CASCADE
                ) ENGINE=InnoDB COMMENT='列车停靠站表（动态路由核心 — stop_index 对应位图偏移量）';
            ''')

            # ---- users ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id     VARCHAR(50)  PRIMARY KEY             COMMENT '用户唯一 ID',
                    username    VARCHAR(50)  NOT NULL UNIQUE         COMMENT '登录账号',
                    password    VARCHAR(256) NOT NULL                COMMENT '登录密码（PBKDF2-SHA256 哈希，格式 salt$hex）',
                    role_type   VARCHAR(20)  DEFAULT 'USER'          COMMENT '角色标识：ADMIN / USER',
                    create_time TIMESTAMP    DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间'
                ) ENGINE=InnoDB COMMENT='全局用户与权限表';
            ''')

            # ---- transaction_logs（金融级流水账本） ----
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transaction_logs (
                    log_id      BIGINT AUTO_INCREMENT PRIMARY KEY     COMMENT '流水主键',
                    order_id    VARCHAR(64)   NOT NULL                COMMENT '关联订单号',
                    user_id     VARCHAR(64)   NOT NULL                COMMENT '操作人 ID',
                    action_type VARCHAR(10)   NOT NULL                COMMENT '动作类型：PAY / REFUND',
                    amount      DECIMAL(10,2) NOT NULL                COMMENT '金额变动（正数）',
                    snapshot_bitmap INT        DEFAULT 0              COMMENT '触发时刻的 buy_mask 快照（审计留痕）',
                    create_time TIMESTAMP     DEFAULT CURRENT_TIMESTAMP COMMENT '流水创建时间',
                    INDEX idx_order (order_id),
                    INDEX idx_user  (user_id),
                    INDEX idx_time  (create_time)
                ) ENGINE=InnoDB COMMENT='金融级流水账本（审计追踪）';
            ''')
            # V3.3 兼容旧表：若缺少 snapshot_bitmap 列，自动补齐
            try:
                cursor.execute(
                    """ALTER TABLE transaction_logs
                       ADD COLUMN snapshot_bitmap INT DEFAULT 0
                       COMMENT '触发时刻的 buy_mask 快照（审计留痕）'"""
                )
            except Exception:
                pass  # 列已存在则忽略

            # ---- 财务核算视图 (View) ----
            cursor.execute('''
                CREATE OR REPLACE VIEW v_daily_financial_report AS
                SELECT
                    t.train_id,
                    CURDATE() AS sale_date,
                    COUNT(o.order_id) AS total_orders,
                    SUM(CASE WHEN o.status = 1 THEN 1 ELSE 0 END) AS paid_orders,
                    SUM(CASE WHEN o.status = 2 THEN 1 ELSE 0 END) AS refunded_orders,
                    /* 总销售额：统计所有订单的流水（无论是否退票，反映真实营收轨迹） */
                    COALESCE(SUM(o.price), 0) AS total_sales,
                    /* 退款额：只统计已退票的 */
                    COALESCE(SUM(CASE WHEN o.status = 2 THEN o.price ELSE 0 END), 0) AS refund_amount,
                    /* 净利润：只统计最后留下来（已支付）的 */
                    COALESCE(SUM(CASE WHEN o.status = 1 THEN o.price ELSE 0 END), 0) AS net_revenue
                FROM train_info t
                LEFT JOIN orders o ON t.train_id = o.train_id
                GROUP BY t.train_id;
            ''')
            print('[ensure_tables] 8 张表 + 1 个财务视图已就绪 (V3.3 触发器引擎)')

            # ---- 注入金融级防篡改触发器 (Triggers) ----
            # 触发器 1：拦截购票动作 (AFTER INSERT)
            cursor.execute('''
                CREATE TRIGGER trg_after_order_insert
                AFTER INSERT ON orders
                FOR EACH ROW
                BEGIN
                    -- 只要新订单的状态是 1 (已支付)，立刻底层自动记账
                    IF NEW.status = 1 THEN
                        INSERT INTO transaction_logs (order_id, user_id, action_type, amount, snapshot_bitmap)
                        VALUES (NEW.order_id, NEW.user_id, 'PAY', NEW.price, NEW.buy_mask);
                    END IF;
                END;
            ''')

            # 触发器 2：拦截退票动作 (AFTER UPDATE)
            cursor.execute('''
                CREATE TRIGGER trg_after_order_update
                AFTER UPDATE ON orders
                FOR EACH ROW
                BEGIN
                    -- 只有当状态被从 1 (已支付) 改为 2 (已退票) 时，才触发退款记账
                    IF OLD.status = 1 AND NEW.status = 2 THEN
                        INSERT INTO transaction_logs (order_id, user_id, action_type, amount, snapshot_bitmap)
                        VALUES (NEW.order_id, NEW.user_id, 'REFUND', NEW.price, NEW.buy_mask);
                    END IF;
                END;
            ''')
            print('[ensure_tables] 数据库底层防篡改触发器 (Triggers) 已挂载完毕！')
    finally:
        conn.close()


# =========================================================================
# 密码哈希工具
# =========================================================================

def _hash_password(pwd: str) -> str:
    """PBKDF2-SHA256 + 随机盐，格式 salt$hex_digest。"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 100000)
    return f'{salt}${dk.hex()}'


# =========================================================================
# 核心：事务内写入固定测试集
# =========================================================================

def populate_sample_data():
    """在单次事务内批量写入 G101 全套测试数据 (V3.0 动态计价)。

    写入内容：
        1a. G101 车次信息（北京南 → 上海虹桥）
        1b. 3 种车型费率（G高铁100/站, D动车60/站, K普快20/站）
        1c. 3 种席别倍率（SWZ商务3.0×, YDZ一等1.6×, EDZ二等1.0×）
        2.  4 个固定经停站（executemany + INSERT IGNORE）
        3.  25 个分级座位（row1→SWZ, row2→YDZ, row3-5→EDZ）
        4.  2 个用户（admin / zhangsan，密码 123456）

    所有 INSERT 均使用 IGNORE / ON DUPLICATE KEY UPDATE 保证幂等。
    任一环节失败则整体 rollback。
    """
    conn = get_connection(autocommit=False)
    try:
        conn.begin()
        with conn.cursor() as cursor:

            # ──── 1. 写入 G101 车次（幂等） ────
            cursor.execute(
                """INSERT INTO train_info
                   (train_id, train_no, departure, arrival,
                    departure_time, price, total_seats)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     train_no       = VALUES(train_no),
                     departure      = VALUES(departure),
                     arrival        = VALUES(arrival),
                     departure_time = VALUES(departure_time),
                     price          = VALUES(price)""",
                ('G101', 'G101', '北京南', '上海虹桥',
                 '2026-07-01 08:00:00', 300.00, 100)
            )
            print('[1/6] G101 车次已写入')

            # ──── 1b. 写入车型基准费率字典数据 ────
            train_models_data = [
                ('G', '高铁', 100.00),
                ('D', '动车',  60.00),
                ('K', '普快',  20.00),
            ]
            cursor.executemany(
                """INSERT IGNORE INTO train_models (type_code, type_name, base_rate)
                   VALUES (%s, %s, %s)""",
                train_models_data
            )
            print(f'[2/6] {len(train_models_data)} 种车型费率已写入')

            # ──── 1c. 写入座位等级倍率字典数据 ────
            seat_classes_data = [
                ('SWZ', '商务座', 3.0),
                ('YDZ', '一等座', 1.6),
                ('EDZ', '二等座', 1.0),
            ]
            cursor.executemany(
                """INSERT IGNORE INTO seat_classes (class_code, class_name, price_multiplier)
                   VALUES (%s, %s, %s)""",
                seat_classes_data
            )
            print(f'[3/6] {len(seat_classes_data)} 种席别倍率已写入')

            # ──── 2. 批量写入 G101 的 4 个固定经停站 ────
            stops = [
                ('G101', '北京南',   0, None,                      '2026-07-01 08:00:00'),
                ('G101', '济南西',   1, '2026-07-01 10:30:00',    '2026-07-01 10:35:00'),
                ('G101', '南京南',   2, '2026-07-01 13:00:00',    '2026-07-01 13:05:00'),
                ('G101', '上海虹桥', 3, '2026-07-01 15:00:00',     None),
            ]
            cursor.executemany(
                """INSERT IGNORE INTO train_stops
                   (train_id, station_name, stop_index, arrival_time, departure_time)
                   VALUES (%s, %s, %s, %s, %s)""",
                stops
            )
            print(f'[4/6] {len(stops)} 个经停站已写入 (stop_index 0→3)')

            # ──── 3. 动态生成 G101 的 25 个真实座位（3+2 布局，V3.0 分等级） ────
            seat_data = []
            for row in range(1, 6):                              # 排号 1~5
                # V3.0 等级判定：第1排商务座，第2排一等座，3-5排二等座
                if row == 1:
                    class_code = 'SWZ'   # 商务座 (3.0×)
                elif row == 2:
                    class_code = 'YDZ'   # 一等座 (1.6×)
                else:
                    class_code = 'EDZ'   # 二等座 (1.0×)

                for col in ['A', 'B', 'C', 'D', 'F']:            # 列名 A/B/C/D/F
                    seat_no = f"{row:02d}{col}"                   # → 01A ~ 05F
                    seat_data.append(('G101', 1, seat_no, class_code, 0, 0))

            cursor.executemany(
                """INSERT INTO seat_status
                   (train_id, carriage_no, seat_no, class_code, seat_bitmap, default_mask)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     class_code = VALUES(class_code),
                     seat_bitmap = 0, default_mask = 0""",
                seat_data
            )
            print(f'[5/6] {len(seat_data)} 个座位已写入 (01A~05F, SWZ×5 + YDZ×5 + EDZ×15)')

            # ──── 4. 写入 2 个用户（密码均为 123456） ────
            users = [
                ('U_ADMIN_001', 'admin',    _hash_password('123456'), 'ADMIN'),
                ('U_PASS_001',  'zhangsan', _hash_password('123456'), 'USER'),
            ]
            cursor.executemany(
                """INSERT IGNORE INTO users
                   (user_id, username, password, role_type)
                   VALUES (%s, %s, %s, %s)""",
                users
            )
            print(f'[6/6] {len(users)} 个用户已写入 (admin / zhangsan)')

            # ──── 提交 ────
            conn.commit()
            total_seats = len(seat_data)
            print(f'[populate] 事务提交成功 — '
                  f'G101 车次 + {len(stops)} 站 + {total_seats} 座 + {len(users)} 用户')

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f'[populate] 事务回滚: {e}')
        raise
    finally:
        conn.close()


# =========================================================================
# 一键重置
# =========================================================================

def reset_all_data():
    """DROP 全部 5 张表 → 重建 DDL → 写入测试集。"""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS orders')
            cursor.execute('DROP TABLE IF EXISTS transaction_logs')
            cursor.execute('DROP TRIGGER IF EXISTS trg_after_order_insert')
            cursor.execute('DROP TRIGGER IF EXISTS trg_after_order_update')
            cursor.execute('DROP TABLE IF EXISTS seat_status')
            cursor.execute('DROP TABLE IF EXISTS train_stops')
            cursor.execute('DROP TABLE IF EXISTS train_info')
            cursor.execute('DROP TABLE IF EXISTS train_models')
            cursor.execute('DROP TABLE IF EXISTS seat_classes')
            cursor.execute('DROP TABLE IF EXISTS users')
        print('[reset] 已 DROP 全部 8 张表')
    finally:
        conn.close()

    ensure_tables()
    populate_sample_data()
    print('[reset] 重建完成 — G101 固定测试集已就绪')


def ensure_sample_data():
    """幂等初始化：建表 + 写入测试集。"""
    ensure_tables()
    populate_sample_data()


# =========================================================================
# CLI 入口
# =========================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='TrainTicketSystem — 数据库初始化与重置脚本'
    )
    parser.add_argument(
        '--reset', action='store_true',
        help='强制 DROP 全部表后重建（数据将丢失）'
    )
    args = parser.parse_args()

    if args.reset:
        reset_all_data()
    else:
        ensure_sample_data()
