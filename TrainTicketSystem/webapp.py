import hashlib
import secrets
import uuid
from decimal import Decimal

from flask import Flask, request, jsonify, render_template, session

app = Flask(__name__)
app.secret_key = 'any_secret_string_you_like'

from utils.db_helper import get_connection
from services.ticket_service import query_seats, query_trains


# ---------------------------------------------------------------------------
# 密码哈希工具（PBKDF2-SHA256 + 随机盐）
# 格式：salt$key_hex  （$ 作分隔符，避免与 hash 字符集冲突）
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 对明文密码做哈希，返回 salt$hex_digest。"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f'{salt}${dk.hex()}'


def verify_password(password: str, stored: str) -> bool:
    """验证明文密码是否与存储的哈希匹配。"""
    try:
        salt, key_hex = stored.split('$', 1)
        dk = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), salt.encode(), 100000
        )
        return dk.hex() == key_hex
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# 预计算的种子密码哈希（密码均为 123456，仅在首次初始化时使用）
# ---------------------------------------------------------------------------
SEED_HASH_ADMIN    = '288052b09d64a961a42e4e5de7d70ae6$1f7343fb176383d4ade2b7975dc7ef396f40de16df06c961923ae8a42573cbe9'
SEED_HASH_ZHANGSAN = '0a16b61920e16db5dc3acf48a4738190$b0185fe570548a62d3d2f8e0891cffde538d0c79d0023ebf59a268ccbb2f6345'


def lookup_user(username, password):
    """从 users 表查询用户（使用哈希密码比对）；若查询失败则回退到内置测试账户。"""
    conn = None
    try:
        conn = get_connection(autocommit=True)
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    "SELECT user_id, role_type, password FROM users WHERE username = %s LIMIT 1",
                    (username,)
                )
                r = cursor.fetchone()
                if r:
                    if isinstance(r, dict):
                        db_user_id = r.get('user_id') or username
                        db_role = r.get('role_type') or 'USER'
                        db_pwd = r.get('password', '')
                    else:
                        db_user_id = r[0]
                        db_role = r[1]
                        db_pwd = r[2] if len(r) > 2 else ''
                    # 尝试哈希比对；若失败则回退到明文比对（兼容旧数据）
                    if verify_password(password, db_pwd):
                        return db_user_id, db_role
                    if db_pwd == password:   # 明文兜底，迁移期可用
                        return db_user_id, db_role
            except Exception:
                pass
    finally:
        if conn:
            conn.close()

    # 回退硬编码账户（数据库不可用时的兜底方案）
    if username == 'admin' and verify_password(password, SEED_HASH_ADMIN):
        return 'admin', 'ADMIN'
    if username == 'zhangsan' and verify_password(password, SEED_HASH_ZHANGSAN):
        return 'zhangsan', 'USER'
    return None, None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/seats')
def api_seats():
    train_id = request.args.get('train_id', 'G101')
    return jsonify(query_seats(train_id))


@app.route('/api/trains', methods=['GET'])
def api_trains():
    """返回所有车次信息（无需鉴权），供前端下拉选择使用。"""
    try:
        return jsonify(query_trains())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/add_train', methods=['POST'])
def api_add_train():
    """管理员接口：发布新车次（V3.1 — 支持自定义定价覆盖 + 事务写入）。

    请求体（JSON）：
        train_id      -- 车次编号（必填）
        custom_price  -- 自定义基准价 元/站（选填，0 或留空则按 G/D/K 前缀自动定价）
        departure_time-- 首发时间 (datetime string)
        stops         -- 经停站数组 [
            {"station_name": "北京南", "arr": null,             "dep": "2026-07-01T08:00"},
            ...
        ]
        train_no      -- 车次号（可选，默认同 train_id）
        total_seats   -- 总座位数（可选，默认 25）

    定价熔断逻辑：
        custom_price > 0 → train_info.price = custom_price（覆盖自动定价）
        custom_price = 0 → train_info.price = 0（计价时走 train_models.base_rate）

    事务动作（任一失败则全部 rollback）：
        1. INSERT/UPDATE train_info
        2. DELETE + INSERT train_stops（按 stop_index 顺序写入）
        3. DELETE + INSERT seat_status × 25（SWZ×5 + YDZ×5 + EDZ×15）
    """
    role = session.get('role')
    if role != 'ADMIN':
        return jsonify({'error': 'forbidden'}), 403

    data = request.json or {}
    train_id = data.get('train_id')
    # 自定义定价覆盖：管理员可为特定车次设定固定基准价，0 表示走自动定价
    custom_price = data.get('custom_price', 0)
    if custom_price is None:
        custom_price = 0
    price = float(custom_price) if custom_price else 0
    departure_time = data.get('departure_time')
    stops = data.get('stops', [])
    train_no = data.get('train_no') or train_id
    total_seats = data.get('total_seats', 25)  # V3.0: 默认 25 座

    # ---- 基础校验 ----
    if not train_id:
        return jsonify({'error': 'train_id required'}), 400
    if len(stops) < 2:
        return jsonify({'error': 'at least 2 stops required (departure + arrival)'}), 400

    # ---- 从经停站推导 departure / arrival ----
    departure = stops[0].get('station_name', '')
    arrival   = stops[-1].get('station_name', '')

    if not departure or not arrival:
        return jsonify({'error': 'each stop must have station_name'}), 400

    # 若未提供 departure_time，用第一站的发车时间兜底
    if not departure_time:
        departure_time = stops[0].get('dep')

    conn = get_connection(autocommit=False)
    try:
        with conn.cursor() as cursor:
            # ──── 1. 写入车次信息 ────
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
                     price          = VALUES(price),
                     total_seats    = VALUES(total_seats)""",
                (train_id, train_no, departure, arrival,
                 departure_time, price, total_seats)
            )

            # ──── 2. 写入经停站（先删后插，保证幂等） ────
            cursor.execute(
                "DELETE FROM train_stops WHERE train_id = %s", (train_id,)
            )
            for idx, stop in enumerate(stops):
                sn = stop.get('station_name', '')
                if not sn:
                    conn.rollback()
                    return jsonify({'error': f'stop[{idx}] missing station_name'}), 400
                cursor.execute(
                    """INSERT INTO train_stops
                       (train_id, station_name, stop_index, arrival_time, departure_time)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (train_id, sn, idx,
                     stop.get('arr') or None,
                     stop.get('dep') or None)
                )

            # ──── 3. 动态生成 25 个分级座位（V3.0: SWZ/YDZ/EDZ） ────
            cursor.execute(
                "DELETE FROM seat_status WHERE train_id = %s", (train_id,)
            )
            seat_count = 0
            for row in range(1, 6):                              # 排号 1~5
                # V3.0 等级判定
                if row == 1:
                    class_code = 'SWZ'   # 商务座 3.0×
                elif row == 2:
                    class_code = 'YDZ'   # 一等座 1.6×
                else:
                    class_code = 'EDZ'   # 二等座 1.0×

                for col in ['A', 'B', 'C', 'D', 'F']:            # 列名 A/B/C/D/F
                    seat_no = f"{row:02d}{col}"                   # → 01A ~ 05F
                    cursor.execute(
                        """INSERT INTO seat_status
                           (train_id, carriage_no, seat_no, class_code, seat_bitmap, default_mask)
                           VALUES (%s, 1, %s, %s, 0, 0)""",
                        (train_id, seat_no, class_code)
                    )
                    seat_count += 1

            # ──── 提交事务 ────
            conn.commit()
            stop_count = len(stops)
            return jsonify({
                'ok': True,
                'train_id': train_id,
                'stops': stop_count,
                'seats': seat_count
            })

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/stops/<train_id>')
def api_stops(train_id):
    """返回指定车次的所有停靠站信息（按 stop_index 排序）。"""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT train_id, station_name, stop_index,
                          arrival_time, departure_time
                   FROM train_stops
                   WHERE train_id = %s
                   ORDER BY stop_index""",
                (train_id,)
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return jsonify([dict(zip(cols, r)) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/get_train_schedule', methods=['GET'])
def api_get_train_schedule():
    """返回指定车次的完整时刻表（所有经停站，按 stop_index 排序）。

    参数：
        train_id  -- 车次编号（必填）

    返回字段：
        stop_index, station_name, arrival_time, departure_time
    """
    train_id = request.args.get('train_id', '').strip()
    if not train_id:
        return jsonify({'error': 'train_id required'}), 400

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT stop_index, station_name, arrival_time, departure_time
                   FROM train_stops
                   WHERE train_id = %s
                   ORDER BY stop_index ASC""",
                (train_id,)
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return jsonify([dict(zip(cols, r)) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/query_routes', methods=['GET'])
def api_query_routes():
    """智能站到站检索：模糊匹配 + 全量浏览双模式。

    模式 A — 模糊检索（from_station 或 to_station 非空）：
        使用 LIKE %keyword% 匹配，输入"北京"可搜到"北京南"。

    模式 B — 浏览全部（两个参数均为空）：
        返回所有车次的首站 → 末站完整路线。

    返回字段：
        train_id, train_no, base_rate,
        departure_time, arrival_time, segment_count,
        from_station_name, to_station_name  ← 真实的匹配/首末站名
    """
    from_station = request.args.get('from_station', '').strip()
    to_station   = request.args.get('to_station', '').strip()

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            if not from_station and not to_station:
                # ──────── 模式 B：浏览全部车次 ────────
                cursor.execute(
                    """SELECT
                           t.train_id,
                           t.train_no,
                           COALESCE(NULLIF(t.price, 0), m.base_rate, 100.00) AS base_rate,
                           s_first.departure_time,
                           s_last.arrival_time,
                           s_first.station_name AS from_station_name,
                           s_last.station_name   AS to_station_name,
                           s_last.stop_index - s_first.stop_index AS segment_count
                       FROM train_info t
                       JOIN train_stops s_first
                         ON t.train_id = s_first.train_id AND s_first.stop_index = 0
                       JOIN train_stops s_last
                         ON t.train_id = s_last.train_id
                       LEFT JOIN train_models m
                         ON m.type_code = LEFT(t.train_id, 1)
                       WHERE s_last.stop_index = (
                           SELECT MAX(stop_index) FROM train_stops
                           WHERE train_id = t.train_id
                       )
                       ORDER BY t.train_id"""
                )
            else:
                # ──────── 模式 A：模糊 LIKE 检索 ────────
                # 至少一个字段非空时，另一个空串退化为 %% 匹配全部
                like_from = f"%{from_station}%" if from_station else "%%"
                like_to   = f"%{to_station}%"   if to_station   else "%%"

                cursor.execute(
                    """SELECT
                           t.train_id,
                           t.train_no,
                           COALESCE(NULLIF(t.price, 0), m.base_rate, 100.00) AS base_rate,
                           s_start.departure_time,
                           s_end.arrival_time,
                           s_start.station_name AS from_station_name,
                           s_end.station_name   AS to_station_name,
                           s_end.stop_index - s_start.stop_index AS segment_count
                       FROM train_info t
                       JOIN train_stops s_start
                         ON t.train_id = s_start.train_id
                       JOIN train_stops s_end
                         ON t.train_id = s_end.train_id
                       LEFT JOIN train_models m
                         ON m.type_code = LEFT(t.train_id, 1)
                       WHERE s_start.station_name LIKE %s
                         AND s_end.station_name   LIKE %s
                         AND s_start.stop_index < s_end.stop_index
                       ORDER BY s_start.departure_time""",
                    (like_from, like_to)
                )

            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return jsonify([dict(zip(cols, r)) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/my_orders')
def api_my_orders():
    """返回当前登录用户的所有订单，从 buy_mask 反向解码真实行程区间。

    核心算法（位运算反向解码）：
        start_index = (buy_mask & -buy_mask).bit_length() - 1  — 最右侧1的位置
        end_index   = buy_mask.bit_length()                      — 最左侧1的下一位

    响应字段：
        order_id, train_id, departure, arrival, seat_no,
        price, order_status, buy_mask, create_time, segments
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'not logged in'}), 401

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            # ════════════════════════════════════════════════════
            # 步骤1：查询订单基础信息（联查 seat_status 获取座位号）
            # ════════════════════════════════════════════════════
            cursor.execute(
                """SELECT
                       o.order_id,
                       o.train_id,
                       s.seat_no,
                       o.price,
                       o.order_status,
                       o.buy_mask,
                       o.create_time
                   FROM orders o
                   LEFT JOIN seat_status s ON o.seat_id = s.seat_id
                   WHERE o.user_id = %s
                   ORDER BY o.create_time DESC""",
                (user_id,)
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            orders = [dict(zip(cols, r)) for r in rows]

            if not orders:
                return jsonify([])

            # ════════════════════════════════════════════════════
            # 步骤2：全量加载涉及车次的停靠站字典（内存缓存）
            #        stops_dict[train_id][stop_index] = station_name
            # ════════════════════════════════════════════════════
            train_ids = list({o['train_id'] for o in orders if o.get('train_id')})
            if not train_ids:
                return jsonify(orders)

            placeholders = ','.join(['%s'] * len(train_ids))
            cursor.execute(
                f"""SELECT train_id, station_name, stop_index
                    FROM train_stops
                    WHERE train_id IN ({placeholders})
                    ORDER BY train_id, stop_index""",
                train_ids
            )
            stops_dict = {}
            for tid, station_name, stop_index in cursor.fetchall():
                stops_dict.setdefault(tid, {})[stop_index] = station_name

            # ════════════════════════════════════════════════════
            # 步骤3 + 4：位运算反向解码 → 组装真实行程
            # ════════════════════════════════════════════════════
            for o in orders:
                buy_mask = o.get('buy_mask', 0) or 0
                tid = o.get('train_id', '')
                stop_map = stops_dict.get(tid, {})

                if buy_mask > 0 and stop_map:
                    # 最右侧1的位置 → 上车站 stop_index
                    start_index = (buy_mask & -buy_mask).bit_length() - 1
                    # 最左侧1的下一位 → 下车站 stop_index
                    end_index = buy_mask.bit_length()

                    o['departure'] = stop_map.get(start_index, '?')
                    o['arrival']   = stop_map.get(end_index, '?')
                    o['segments']  = end_index - start_index
                else:
                    o['departure'] = '?'
                    o['arrival']   = '?'

            return jsonify(orders)

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/buy', methods=['POST'])
def api_buy():
    """购票接口（动态路由版本）。

    请求体（JSON）：
        train_id      -- 车次编号（必填）
        seat_no       -- 座位号，如 '01A'（必填）
        start_station -- 上车站名称（与 buy_mask 二选一；优先使用车站）
        end_station   -- 下车站名称（与 buy_mask 二选一；优先使用车站）
        buy_mask      -- 手动指定掩码（兼容旧版；当 start/end 均未提供时生效）
        carriage_no   -- 车厢号（可选，默认 1）
        user_id       -- 用户 ID（可选，session 或默认 'WEBUSER'）

    响应：
        成功 → {"success": true, "order_id": "ORD...", "buy_mask": 3, "segments": 2}
        失败 → {"success": false, "reason": "..."}, HTTP 400
    """
    data = request.json or {}
    user_id = session.get('user_id') or data.get('user_id') or 'WEBUSER'
    train_id = data.get('train_id')
    carriage_no = int(data.get('carriage_no', 1))
    seat_no = data.get('seat_no')
    start_station = data.get('start_station')
    end_station = data.get('end_station')

    # ---- 基本参数校验 ----
    if not train_id or not seat_no:
        return jsonify({'success': False, 'reason': 'train_id and seat_no required'}), 400

    # ---- 掩码计算：优先使用车站名 → 动态计算；否则回退到手动 buy_mask ----
    if start_station and end_station:
        # ──────── 动态路由模式 ────────
        conn = get_connection(autocommit=True)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT station_name, stop_index
                       FROM train_stops
                       WHERE train_id = %s
                       ORDER BY stop_index""",
                    (train_id,)
                )
                stops = cursor.fetchall()  # [(station_name, stop_index), ...]
        finally:
            conn.close()

        if not stops:
            return jsonify({
                'success': False,
                'reason': f'车次 {train_id} 未配置停靠站数据，请使用 buy_mask 手动指定掩码'
            }), 400

        # 构建 站名 → 序号 映射
        station_map = {row[0]: row[1] for row in stops}

        start_idx = station_map.get(start_station)
        end_idx   = station_map.get(end_station)

        # ---- 合法性校验 ----
        if start_idx is None:
            available = ', '.join(station_map.keys())
            return jsonify({
                'success': False,
                'reason': f'起点站 "{start_station}" 不在车次 {train_id} 的停靠列表中。可选: {available}'
            }), 400

        if end_idx is None:
            available = ', '.join(station_map.keys())
            return jsonify({
                'success': False,
                'reason': f'终点站 "{end_station}" 不在车次 {train_id} 的停靠列表中。可选: {available}'
            }), 400

        if end_idx <= start_idx:
            return jsonify({
                'success': False,
                'reason': f'终点站 "{end_station}" (stop_index={end_idx}) 必须在起点站 "{start_station}" (stop_index={start_idx}) 之后'
            }), 400

        # ---- 核心算法：动态计算位图掩码 ----
        # 公式: buy_mask = ((1 << (end_idx - start_idx)) - 1) << start_idx
        # 示例：start_idx=0, end_idx=1 → ((1<<1)-1)<<0 = 1    (bit0，北京→济南)
        #       start_idx=0, end_idx=3 → ((1<<3)-1)<<0 = 7    (bit0+1+2，北京→上海)
        #       start_idx=1, end_idx=2 → ((1<<1)-1)<<1 = 2    (bit1，济南→南京)
        segment_count = end_idx - start_idx
        buy_mask = ((1 << segment_count) - 1) << start_idx

    else:
        # ──────── 兼容旧版：直接传入 buy_mask ────────
        buy_mask = data.get('buy_mask')
        if buy_mask is None:
            return jsonify({
                'success': False,
                'reason': '请提供 start_station+end_station（推荐），或 buy_mask（手动掩码）'
            }), 400

        if isinstance(buy_mask, str):
            buy_mask = buy_mask.strip()
            if buy_mask.startswith('0b'):
                buy_mask = int(buy_mask, 2)
            elif buy_mask.startswith('0x'):
                buy_mask = int(buy_mask, 16)
            else:
                buy_mask = int(buy_mask)
        else:
            buy_mask = int(buy_mask or 0)
        segment_count = None  # 手动模式下无法知道区间数

    # ════════════════════════════════════════════════════════════
    # 执行购票事务：悲观锁 + 冲突检测 → 扣减库存 → 服务端重新计价 → 安全入账
    # ════════════════════════════════════════════════════════════
    conn = get_connection(autocommit=False)
    try:
        conn.begin()
        with conn.cursor() as cursor:
            # ── 1. 锁定座位行，获取 seat_id / 当前位图 / 席别代码 ──
            cursor.execute(
                """SELECT seat_id, seat_bitmap, class_code
                   FROM seat_status
                   WHERE train_id = %s AND seat_no = %s
                   FOR UPDATE""",
                (train_id, seat_no)
            )
            seat_row = cursor.fetchone()

            if not seat_row:
                conn.rollback()
                return jsonify({
                    'success': False,
                    'reason': f'座位 {seat_no} 在车次 {train_id} 中不存在'
                }), 400

            seat_id = seat_row[0]
            current_bitmap = seat_row[1] or 0
            class_code = seat_row[2] or 'EDZ'

            # ── 2. Python 层内存冲突检测（关键防线，杜绝超卖） ──
            if (current_bitmap & buy_mask) != 0:
                conn.rollback()
                return jsonify({
                    'success': False,
                    'reason': '座位区间冲突（该区间已被他人购买）'
                }), 400

            # ── 3. 按位或扣减库存（先锁定库存，防止并发） ──
            new_bitmap = current_bitmap | buy_mask
            cursor.execute(
                """UPDATE seat_status
                   SET seat_bitmap = %s
                   WHERE seat_id = %s""",
                (new_bitmap, seat_id)
            )

            # ── 4. 服务端重新计价（绝对安全：不信任前端任何金额） ──
            #  4a. 查基准价（特权熔断：管理员自定义 > 前缀自动定价 > 兜底 100）
            cursor.execute(
                """SELECT COALESCE(NULLIF(ti.price, 0), tm.base_rate, 100.00) AS base_rate
                   FROM train_info ti
                   LEFT JOIN train_models tm ON tm.type_code = LEFT(ti.train_id, 1)
                   WHERE ti.train_id = %s""",
                (train_id,)
            )
            rate_row = cursor.fetchone()
            base_rate = rate_row[0] if rate_row else 100.00

            #  4b. 查 seat_classes 获取当前座位等级倍率
            cursor.execute(
                "SELECT price_multiplier FROM seat_classes WHERE class_code = %s",
                (class_code,)
            )
            mult_row = cursor.fetchone()
            price_multiplier = mult_row[0] if mult_row else 1.0

            #  4c. 站数差（段数）：优先用动态路由计算值，手动掩码模式则用位计数兜底
            segs = segment_count if segment_count is not None else bin(buy_mask).count('1')

            #  4d. 高精度 Decimal 计价（杜绝浮点误差写入 DECIMAL 列）
            actual_price = (
                Decimal(str(segs))
                * Decimal(str(base_rate))
                * Decimal(str(price_multiplier))
            ).quantize(Decimal('0.00'))

            # ── 5. 安全入账：写入订单（金额为服务端二次计算结果） ──
            order_id = 'ORD' + uuid.uuid4().hex[:10].upper()
            cursor.execute(
                """INSERT INTO orders
                   (order_id, user_id, train_id, seat_id, buy_mask, price, order_status, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'PAID', 1)""",
                (order_id, user_id, train_id, seat_id, buy_mask, actual_price)
            )

            # ── 5b. 写入金融级流水账本（审计追踪） ──
            cursor.execute(
                """INSERT INTO transaction_logs
                   (order_id, user_id, action_type, amount)
                   VALUES (%s, %s, 'PAY', %s)""",
                (order_id, user_id, actual_price)
            )

            # ── 6. 提交事务 ──
            conn.commit()

            resp = {
                'success': True,
                'order_id': order_id,
                'buy_mask': buy_mask,
                'price': actual_price,
                'class_code': class_code,
                'segments': segs
            }
            return jsonify(resp)

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({
            'success': False,
            'reason': f'系统异常：{e}'
        }), 500
    finally:
        conn.close()


@app.route('/api/refund', methods=['POST'])
def api_refund():
    """退票接口 — 纯 Python 事务控制（不再依赖数据库触发器）。

    ADMIN：可退任意订单。
    USER：  只能退自己的订单。

    核心事务流程：
        1. 开启显式事务 conn.begin()
        2. SELECT ... FOR UPDATE 锁定订单行（带 order_status='PAID' 防重）
        3. 校验 seat_id 非空、权限合法
        4. UPDATE orders → REFUNDED（rowcount 必须 == 1）
        5. UPDATE seat_status SET seat_bitmap = seat_bitmap ^ buy_mask（rowcount 必须 == 1）
        6. conn.commit()（任何异常回滚，保证库存与订单的强一致性）
    """
    order_id = request.json.get('order_id')
    if not order_id:
        return jsonify({'error': 'order_id required'}), 400

    role = session.get('role')
    current_user_id = session.get('user_id')

    if not role:
        return jsonify({'error': 'forbidden — 请先登录'}), 403

    conn = get_connection(autocommit=False)
    try:
        # ════════════════════════════════════════════════════════
        # 步骤 1：开启显式事务
        # ════════════════════════════════════════════════════════
        conn.begin()

        with conn.cursor() as cursor:
            # ════════════════════════════════════════════════════
            # 步骤 2：SELECT ... FOR UPDATE 锁定订单行
            #         带 order_status='PAID' 防重复退票
            # ════════════════════════════════════════════════════
            cursor.execute(
                """SELECT user_id, seat_id, buy_mask, price
                   FROM orders
                   WHERE order_id = %s AND order_status = 'PAID'
                   FOR UPDATE""",
                (order_id,)
            )
            row = cursor.fetchone()

            if not row:
                conn.rollback()
                return jsonify({'error': '订单不存在或已退票'}), 404

            owner_id, seat_id, buy_mask, refund_price = row

            # ════════════════════════════════════════════════════
            # 步骤 3：数据完整性 + 权限校验
            # ════════════════════════════════════════════════════
            if seat_id is None:
                conn.rollback()
                return jsonify({'error': '订单数据异常：seat_id 为空，无法释放库存'}), 500

            if role == 'ADMIN':
                pass  # 管理员可退任意订单
            elif role == 'USER':
                if not current_user_id or owner_id != current_user_id:
                    conn.rollback()
                    return jsonify({'error': '无权操作：该订单不属于你'}), 403
            else:
                conn.rollback()
                return jsonify({'error': 'forbidden — 未知角色'}), 403

            # ════════════════════════════════════════════════════
            # 步骤 4：更新订单状态（rowcount 强校验）
            # ════════════════════════════════════════════════════
            affected_orders = cursor.execute(
                """UPDATE orders
                   SET order_status = 'REFUNDED', status = 2
                   WHERE order_id = %s AND order_status = 'PAID'""",
                (order_id,)
            )
            if affected_orders != 1:
                conn.rollback()
                return jsonify({'error': '退票失败：订单状态异常（可能已被并发退票）'}), 409

            # ════════════════════════════════════════════════════
            # 步骤 5：库存释放 —— 位图异或 ^ 运算（rowcount 强校验）
            #
            # 购票时: seat_bitmap = seat_bitmap | buy_mask   (OR  置位)
            # 退票时: seat_bitmap = seat_bitmap ^ buy_mask   (XOR 清零)
            # ════════════════════════════════════════════════════
            affected_seats = cursor.execute(
                """UPDATE seat_status
                   SET seat_bitmap = seat_bitmap ^ %s
                   WHERE seat_id = %s""",
                (buy_mask, seat_id)
            )
            if affected_seats != 1:
                conn.rollback()
                return jsonify({'error': '退票失败：座位记录丢失，无法释放库存'}), 500

            # 写入金融级流水账本（审计追踪）
            cursor.execute(
                """INSERT INTO transaction_logs
                   (order_id, user_id, action_type, amount)
                   VALUES (%s, %s, 'REFUND', %s)""",
                (order_id, owner_id, refund_price)
            )

            # ════════════════════════════════════════════════════
            # 步骤 6：提交事务
            # ════════════════════════════════════════════════════
            conn.commit()

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

    return jsonify({'ok': True})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user_id, role = lookup_user(username, password)
    if user_id and role:
        session['role'] = role.upper()
        session['user_id'] = user_id
        session['username'] = username
        return jsonify({
            'success': True,
            'role': role.upper(),
            'username': username
        })
    else:
        return jsonify({'success': False, 'message': '账号或密码错误'})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/financial')
def api_financial():
    role = session.get('role')
    if role != 'ADMIN':
        return jsonify({'error': 'forbidden'}), 403

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    'SELECT * FROM v_daily_financial_report LIMIT 100'
                )
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
                return jsonify([dict(zip(cols, r)) for r in rows])
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/finance/logs')
def api_finance_logs():
    """金融级流水账本：按时间倒序返回最近 100 条流水记录。

    返回字段：
        log_id, order_id, user_id, action_type, amount, create_time
    """
    role = session.get('role')
    if role != 'ADMIN':
        return jsonify({'error': 'forbidden'}), 403

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT log_id, order_id, user_id, action_type, amount, create_time
                   FROM transaction_logs
                   ORDER BY create_time DESC
                   LIMIT 100"""
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return jsonify([dict(zip(cols, r)) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
