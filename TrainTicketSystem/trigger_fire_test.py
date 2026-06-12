import os
import pymysql
from pymysql.cursors import DictCursor

def get_conn():
    host = os.getenv('DB_HOST', '127.0.0.1')
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    db = os.getenv('DB_NAME', 'train_ticket')
    return pymysql.connect(host=host, user=user, password=password, database=db, autocommit=True)

def fire_trigger_on_latest():
    conn = get_conn()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute('SELECT order_id, seat_id, buy_mask, status FROM orders ORDER BY create_time DESC LIMIT 1')
            o = cursor.fetchone()
            if not o:
                print('No orders found')
                return
            print('Before change:', o)
            order_id = o['order_id']
            seat_id = o['seat_id']

            # 回置为非退款状态（1），然后再更新为 2 触发触发器
            cursor.execute('UPDATE orders SET status = 1 WHERE order_id = %s', (order_id,))
            cursor.execute('UPDATE orders SET status = 2 WHERE order_id = %s', (order_id,))

            cursor.execute('SELECT seat_bitmap FROM seat_status WHERE seat_id = %s', (seat_id,))
            s = cursor.fetchone()
            print('After trigger, seat_bitmap =', s['seat_bitmap'] if s else None)
    finally:
        conn.close()

if __name__ == "__main__":
    fire_trigger_on_latest()
