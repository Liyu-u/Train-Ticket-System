import hashlib
import secrets

from flask import Flask, request, jsonify, render_template, session

app = Flask(__name__)
app.secret_key = 'any_secret_string_you_like'

from utils.db_helper import get_connection
from services.order_service import buy_ticket
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
    """管理员接口：发布新车次（事务性写入车次 + 经停站 + 默认座位）。

    请求体（JSON）：
        train_id      -- 车次编号（必填）
        price         -- 票价
        departure_time-- 首发时间 (datetime string)
        stops         -- 经停站数组 [
            {"station_name": "北京南", "arr": null,             "dep": "2026-07-01T08:00"},
            {"station_name": "济南西", "arr": "2026-07-01T10:30", "dep": "2026-07-01T10:35"},
            ...
        ]
        train_no      -- 车次号（可选，默认同 train_id）
        total_seats   -- 总座位数（可选，默认 100）

    事务动作（任一失败则全部 rollback）：
        1. INSERT/UPDATE train_info
        2. DELETE + INSERT train_stops（重新发布时覆盖旧停靠站）
        3. DELETE + INSERT seat_status × 5（默认测试座位，mask 1/2/4/8/16）
    """
    role = session.get('role')
    if role != 'ADMIN':
        return jsonify({'error': 'forbidden'}), 403

    data = request.json or {}
    train_id = data.get('train_id')
    price = data.get('price', 0)
    departure_time = data.get('departure_time')
    stops = data.get('stops', [])
    train_no = data.get('train_no') or train_id
    total_seats = data.get('total_seats', 100)

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

            # ──── 3. 生成 5 个默认测试座位 ────
            cursor.execute(
                "DELETE FROM seat_status WHERE train_id = %s", (train_id,)
            )
            seat_nos = ['01A', '01B', '02A', '02B', '03A']
            masks    = [0b00001, 0b00010, 0b00100, 0b01000, 0b10000]
            for seat_no, mask in zip(seat_nos, masks):
                cursor.execute(
                    """INSERT INTO seat_status
                       (train_id, carriage_no, seat_no, seat_bitmap, default_mask)
                       VALUES (%s, 1, %s, 0, %s)""",
                    (train_id, seat_no, mask)
                )

            # ──── 提交事务 ────
            conn.commit()
            stop_count = len(stops)
            seat_count = len(seat_nos)
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


@app.route('/api/my_orders')
def api_my_orders():
    """返回当前登录用户的所有订单（JOIN train_info + seat_status）。

    响应字段：
        order_id, train_id, departure, arrival, seat_no, carriage_no,
        price, order_status, buy_mask, create_time
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'not logged in'}), 401

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT
                       o.order_id,
                       o.train_id,
                       COALESCE(t.departure, '') AS departure,
                       COALESCE(t.arrival,   '') AS arrival,
                       s.seat_no,
                       s.carriage_no,
                       o.price,
                       o.order_status,
                       o.buy_mask,
                       o.create_time
                   FROM orders o
                   LEFT JOIN train_info t ON o.train_id = t.train_id
                   LEFT JOIN seat_status s ON o.seat_id = s.seat_id
                   WHERE o.user_id = %s
                   ORDER BY o.create_time DESC""",
                (user_id,)
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return jsonify([dict(zip(cols, r)) for r in rows])
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

    # ---- 调用原有购票事务（悲观锁 + 位图冲突检测） ----
    order_id = buy_ticket(user_id, train_id, carriage_no, seat_no, buy_mask)
    if order_id:
        resp = {'success': True, 'order_id': order_id, 'buy_mask': buy_mask}
        if segment_count is not None:
            resp['segments'] = segment_count
        return jsonify(resp)
    else:
        return jsonify({
            'success': False,
            'reason': '座位区间冲突（该区间已被他人购买）或座位不存在'
        }), 400


@app.route('/api/refund', methods=['POST'])
def api_refund():
    """退票接口（支持 ADMIN 任意退 + USER 退自己的票）。

    ADMIN：可退任意订单。
    USER： 必须在 SQL 层面强校验 order_id 归属当前 session['user_id']，
           防止越权退票。
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
        with conn.cursor() as cursor:
            # 先查订单状态（防止重复退票）
            cursor.execute(
                "SELECT user_id, order_status FROM orders WHERE order_id = %s FOR UPDATE",
                (order_id,)
            )
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return jsonify({'error': '订单不存在'}), 404

            owner_id, current_status = row[0], row[1] if len(row) > 1 else None

            if current_status == 'REFUNDED':
                conn.rollback()
                return jsonify({'error': '该订单已退票，不能重复操作'}), 400

            # ── 权限校验 ──
            if role == 'ADMIN':
                pass  # 管理员可退任意订单
            elif role == 'USER':
                if not current_user_id or owner_id != current_user_id:
                    conn.rollback()
                    return jsonify({'error': '无权操作：该订单不属于你'}), 403
            else:
                conn.rollback()
                return jsonify({'error': 'forbidden — 未知角色'}), 403

            # ── 执行退票：双写 status + order_status ──
            cursor.execute(
                """UPDATE orders
                   SET status = 2, order_status = 'REFUNDED'
                   WHERE order_id = %s""",
                (order_id,)
            )
            # 触发器 trg_orders_after_update_refund 会自动释放 seat_bitmap
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


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
