"""
db_setup.py

数据库预置脚本（幂等）：
- 创建所有表（如果不存在），结构与 01_init_db.sql 完全一致
- 插入示例车次 G101, G102, G103
- 为每个车次插入 5 个示例座位（1-01A, 1-01B, 1-02A, 1-02B, 1-03A）
- 为每个座位写入默认掩码（default_mask）: 0b00001, 0b00010, 0b00100, 0b01000, 0b10000
- 初始化 seat_bitmap = 0

同时包含 `reset_all_data()` 用于一键重置样例数据（CLI 支持 `--reset`）。
"""
import argparse
from utils.db_helper import get_connection


def ensure_tables():
    """创建所有表（幂等），DDL 与 sql_scripts/01_init_db.sql 保持一致。"""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
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
                    seat_bitmap   INT          DEFAULT 0          COMMENT '二进制区间占用状态：0=全空闲',
                    default_mask  INT          DEFAULT 0          COMMENT '该座位的默认区间掩码',
                    UNIQUE KEY uk_train_seat (train_id, carriage_no, seat_no)
                ) ENGINE=InnoDB COMMENT='高并发座位区间状态表（位图模型核心）';
            ''')

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
                    status       INT           DEFAULT 1              COMMENT '数值状态：1=已支付, 2=已退票（触发器与视图使用此字段）',
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
                ) ENGINE=InnoDB COMMENT='列车停靠站表（动态路由核心 —— stop_index 对应位图偏移量）';
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
    finally:
        conn.close()


def insert_train_if_not_exists(train_id, train_no, departure, arrival,
                               departure_time, price, total_seats=100):
    """幂等插入车次信息。若已存在则跳过。"""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM train_info WHERE train_id = %s LIMIT 1',
                (train_id,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    """INSERT INTO train_info
                       (train_id, train_no, departure, arrival,
                        departure_time, price, total_seats)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (train_id, train_no, departure, arrival,
                     departure_time, price, total_seats)
                )
                print(f'已插入车次 {train_id}')
            else:
                print(f'车次 {train_id} 已存在，跳过创建')
    finally:
        conn.close()


def insert_seat_if_not_exists(train_id, carriage_no, seat_no, default_mask=0):
    """幂等插入座位。若已存在则重置 seat_bitmap=0 并更新 default_mask。"""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT seat_id FROM seat_status
                   WHERE train_id = %s AND carriage_no = %s AND seat_no = %s""",
                (train_id, carriage_no, seat_no)
            )
            if not cursor.fetchone():
                cursor.execute(
                    """INSERT INTO seat_status
                       (train_id, carriage_no, seat_no, seat_bitmap, default_mask)
                       VALUES (%s, %s, %s, 0, %s)""",
                    (train_id, carriage_no, seat_no, default_mask)
                )
                print(f'已插入座位 {train_id} {carriage_no} {seat_no} '
                      f'mask={bin(default_mask)}')
            else:
                cursor.execute(
                    """UPDATE seat_status SET seat_bitmap = 0, default_mask = %s
                       WHERE train_id = %s AND carriage_no = %s AND seat_no = %s""",
                    (default_mask, train_id, carriage_no, seat_no)
                )
                print(f'座位 {train_id} {carriage_no} {seat_no} 已存在，'
                      f'已重置 seat_bitmap=0 并设置 default_mask={bin(default_mask)}')
    finally:
        conn.close()


def populate_sample_data():
    """插入示例车次与座位数据，同时插入示例用户（使用哈希密码）。"""
    # ---- 车次 ----
    trains = [
        ('G101', 'G101', '北京南',   '上海虹桥', '2026-07-01 08:00:00', 300.00),
        ('G102', 'G102', '上海虹桥', '北京南',   '2026-07-01 13:00:00', 300.00),
        ('G103', 'G103', '北京南',   '杭州东',   '2026-07-01 09:00:00', 180.00),
    ]

    seats = ['01A', '01B', '02A', '02B', '03A']
    masks = [0b00001, 0b00010, 0b00100, 0b01000, 0b10000]

    for t in trains:
        insert_train_if_not_exists(t[0], t[1], t[2], t[3], t[4], t[5])
        for seat_no, mask in zip(seats, masks):
            insert_seat_if_not_exists(t[0], 1, seat_no, mask)

    # ---- 示例用户（密码均为 123456，使用 PBKDF2-SHA256 哈希存储） ----
    _seed_users()

    # ---- 示例停靠站（G101 经停 4 站） ----
    _seed_train_stops()


def _seed_users():
    """幂等插入示例用户（密码使用 PBKDF2-SHA256 哈希存储）。"""
    import hashlib
    import secrets

    def _hash(pwd: str) -> str:
        salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 100000)
        return f'{salt}${dk.hex()}'

    users = [
        ('U_ADMIN_001', 'admin',    '123456', 'ADMIN'),
        ('U_PASS_001',  'zhangsan', '123456', 'USER'),
    ]

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            for uid, uname, pwd, role in users:
                cursor.execute(
                    'SELECT 1 FROM users WHERE user_id = %s LIMIT 1', (uid,)
                )
                if not cursor.fetchone():
                    hashed = _hash(pwd)
                    cursor.execute(
                        """INSERT INTO users (user_id, username, password, role_type)
                           VALUES (%s, %s, %s, %s)""",
                        (uid, uname, hashed, role)
                    )
                    print(f'已插入用户 {uname} (role={role})')
                else:
                    print(f'用户 {uname} 已存在，跳过创建')
    finally:
        conn.close()


def _seed_train_stops():
    """幂等插入 G101 停靠站数据（4 站 → 3 个运行区间）。"""
    stops = [
        ('G101', '北京南',   0, None,                      '2026-07-01 08:00:00'),
        ('G101', '济南西',   1, '2026-07-01 10:30:00',    '2026-07-01 10:35:00'),
        ('G101', '南京南',   2, '2026-07-01 13:00:00',    '2026-07-01 13:05:00'),
        ('G101', '上海虹桥', 3, '2026-07-01 15:00:00',     None),
    ]

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            for train_id, station_name, stop_index, arr, dep in stops:
                cursor.execute(
                    """SELECT 1 FROM train_stops
                       WHERE train_id = %s AND stop_index = %s LIMIT 1""",
                    (train_id, stop_index)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        """INSERT INTO train_stops
                           (train_id, station_name, stop_index, arrival_time, departure_time)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (train_id, station_name, stop_index, arr, dep)
                    )
                    print(f'已插入停靠站 {train_id} [{stop_index}] {station_name}')
                else:
                    print(f'停靠站 {train_id} [{stop_index}] {station_name} 已存在，跳过')
    finally:
        conn.close()


def reset_all_data():
    """彻底重建示例数据（DROP 旧表并重建）。"""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS orders')
            cursor.execute('DROP TABLE IF EXISTS seat_status')
            cursor.execute('DROP TABLE IF EXISTS train_stops')
            cursor.execute('DROP TABLE IF EXISTS train_info')
            cursor.execute('DROP TABLE IF EXISTS users')
        print('已 DROP orders, seat_status, train_stops, train_info, users 表（重建中）')
    finally:
        conn.close()

    ensure_tables()
    populate_sample_data()


def ensure_sample_data():
    """幂等初始化：建表 + 插入示例数据。"""
    ensure_tables()
    populate_sample_data()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='DB setup for TrainTicketSystem')
    parser.add_argument('--reset', action='store_true',
                        help='Reset all sample data (delete and re-create)')
    args = parser.parse_args()

    if args.reset:
        ensure_tables()
        reset_all_data()
    else:
        ensure_sample_data()
