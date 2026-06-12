from flask import Flask, request, jsonify, render_template, session
import os
import json
from main import buy_ticket, get_db_conn

app = Flask(__name__)
app.secret_key = 'any_secret_string_you_like' 


def query_seats(train_id):
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT seat_id, carriage_no, seat_no, seat_bitmap, default_mask FROM seat_status WHERE train_id=%s', (train_id,))
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            result = [dict(zip(cols, r)) for r in rows]
            return result
    finally:
        conn.close()


def lookup_user(username, password):
    """尝试从 users 表查询用户；若不存在则回退到内置测试账户。"""
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor() as cursor:
            try:
                cursor.execute('SELECT user_id, role_type FROM users WHERE username=%s AND password=%s LIMIT 1', (username, password))
                r = cursor.fetchone()
                if r:
                    # 支持不同游标返回格式
                    if isinstance(r, dict):
                        return r.get('user_id') or username, r.get('role_type') or 'user'
                    else:
                        return r[0], r[1]
            except Exception:
                # 如果 users 表不存在或查询失败，则跳过至内置账户
                pass
    finally:
        if conn:
            conn.close()

    # 回退硬编码账户（方便演示）
    if username == 'admin' and password == '123456':
        return 'admin', 'admin'
    if username == 'zhangsan' and password == '123456':
        return 'zhangsan', 'user'
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
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            # 兼容不同脚本可能存在的列名差异，使用 IFNULL/COALESCE
            cursor.execute(
                """
                SELECT
                    train_id,
                    IFNULL(train_no, train_id) AS train_no,
                    IFNULL(departure, start_station) AS departure_station,
                    IFNULL(arrival, end_station) AS arrival_station,
                    IFNULL(price, 0) AS price,
                    IFNULL(total_seats, 0) AS total_seats,
                    departure_time
                FROM train_info
                ORDER BY train_id
                """
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            result = [dict(zip(cols, r)) for r in rows]
            return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/add_train', methods=['POST'])
def api_add_train():
    """管理员接口：新增或更新车次信息。要求 session 中 role 为 admin。"""
    role = session.get('role')
    if role != 'admin':
        return jsonify({'error': 'forbidden'}), 403

    data = request.json or {}
    train_id = data.get('train_id')
    train_no = data.get('train_no') or train_id
    departure = data.get('departure') or data.get('departure_station')
    arrival = data.get('arrival') or data.get('arrival_station')
    departure_time = data.get('departure_time')
    price = data.get('price')
    total_seats = data.get('total_seats')

    if not train_id or not departure or not arrival:
        return jsonify({'error': 'train_id, departure and arrival required'}), 400

    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            # 使用 INSERT ... ON DUPLICATE KEY UPDATE 保证幂等覆盖
            cursor.execute(
                '''
                INSERT INTO train_info (train_id, train_no, departure, arrival, departure_time, price, total_seats)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  train_no = VALUES(train_no),
                  departure = VALUES(departure),
                  arrival = VALUES(arrival),
                  departure_time = VALUES(departure_time),
                  price = VALUES(price),
                  total_seats = VALUES(total_seats)
                ''',
                (train_id, train_no, departure, arrival, departure_time, price, total_seats)
            )
            conn.commit()
            return jsonify({'ok': True, 'train_id': train_id})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/buy', methods=['POST'])
def api_buy():
    data = request.json or {}
    # 优先使用已登录用户
    user_id = session.get('user_id') or data.get('user_id') or 'WEBUSER'
    train_id = data.get('train_id')
    carriage_no = int(data.get('carriage_no', 1))
    seat_no = data.get('seat_no')
    # buy_mask can be provided as binary string '00110' or integer
    buy_mask = data.get('buy_mask')
    if isinstance(buy_mask, str):
        if buy_mask.startswith('0b'):
            buy_mask = int(buy_mask, 2)
        else:
            buy_mask = int(buy_mask, 2)
    else:
        buy_mask = int(buy_mask or 0)

    order_id = buy_ticket(user_id, train_id, carriage_no, seat_no, buy_mask)
    if order_id:
        return jsonify({'success': True, 'order_id': order_id})
    else:
        return jsonify({'success': False}), 400


@app.route('/api/refund', methods=['POST'])
def api_refund():
    order_id = request.json.get('order_id')
    if not order_id:
        return jsonify({'error': 'order_id required'}), 400
    # 仅管理员可退票
    role = session.get('role')
    if role != 'admin':
        return jsonify({'error': 'forbidden'}), 403
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('UPDATE orders SET status = 2 WHERE order_id = %s', (order_id,))
            conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    # 强制判定身份
    if username == 'admin' and password == '123456':
        # 写入 session 以保持后端受保护接口的权限一致性
        session['role'] = 'admin'
        session['user_id'] = 'admin'
        session['username'] = 'admin'
        return jsonify({"success": True, "role": "admin", "username": "admin"})
    elif username == 'zhangsan' and password == '123456':
        session['role'] = 'user'
        session['user_id'] = 'zhangsan'
        session['username'] = 'zhangsan'
        return jsonify({"success": True, "role": "user", "username": "zhangsan"})
    else:
        return jsonify({"success": False, "message": "账号或密码错误"})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/financial')
def api_financial():
    # 仅管理员可查看财务视图
    role = session.get('role')
    if role != 'admin':
        return jsonify({'error': 'forbidden'}), 403
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute('SELECT * FROM v_daily_financial_report LIMIT 100')
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
                return jsonify([dict(zip(cols, r)) for r in rows])
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)