"""
trigger_fire_test.py

测试退票触发器：选择最近订单，先重置 status=1，再更新为 status=2，
观察触发器是否恢复了 seat_status 中的位图。
"""
from utils.db_helper import get_connection
from pymysql.cursors import DictCursor


def fire_trigger_on_latest():
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(
                """SELECT order_id, seat_id, buy_mask, status
                   FROM orders ORDER BY create_time DESC LIMIT 1"""
            )
            o = cursor.fetchone()
            if not o:
                print('No orders found')
                return
            print('Before change:', o)
            order_id = o['order_id']
            seat_id = o['seat_id']

            # 回置为非退款状态（1），然后再更新为 2 触发触发器
            cursor.execute(
                "UPDATE orders SET status = 1, order_status = 'PAID' "
                "WHERE order_id = %s",
                (order_id,)
            )
            cursor.execute(
                "UPDATE orders SET status = 2, order_status = 'REFUNDED' "
                "WHERE order_id = %s",
                (order_id,)
            )

            cursor.execute(
                "SELECT seat_bitmap FROM seat_status WHERE seat_id = %s",
                (seat_id,)
            )
            s = cursor.fetchone()
            print('After trigger, seat_bitmap =',
                  s['seat_bitmap'] if s else None)
    finally:
        conn.close()


if __name__ == "__main__":
    fire_trigger_on_latest()
