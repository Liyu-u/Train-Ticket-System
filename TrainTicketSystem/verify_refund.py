"""
verify_refund.py

用途：选择最近创建的订单，将其状态更新为已退票（status=2, order_status='REFUNDED'），
并验证触发器是否已将对应座位的 seat_bitmap 恢复为 0。

使用方法：在 `TrainTicketSystem` 目录下运行：
    python verify_refund.py
"""
from utils.db_helper import get_connection
import pymysql


def verify():
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """SELECT order_id, seat_id, train_id
                   FROM orders ORDER BY create_time DESC LIMIT 1"""
            )
            o = cursor.fetchone()
            if not o:
                print('未找到订单，无法验证。')
                return
            order_id = o['order_id']
            seat_id = o['seat_id']
            train_id = o['train_id']
            print(f'选定订单 {order_id} 对应 seat_id={seat_id}, train_id={train_id}，'
                  f'将其状态更新为已退票')

            # 双写：同时设置 status=2 和 order_status='REFUNDED'
            cursor.execute(
                """UPDATE orders
                   SET status = 2, order_status = 'REFUNDED'
                   WHERE order_id = %s""",
                (order_id,)
            )

            # 等待触发器生效（通常同步）
            cursor.execute(
                "SELECT seat_bitmap FROM seat_status WHERE seat_id = %s",
                (seat_id,)
            )
            s = cursor.fetchone()
            if s:
                print('当前 seat_bitmap =', s['seat_bitmap'])
                if s['seat_bitmap'] == 0:
                    print('✅ 触发器生效：seat_bitmap 已恢复为 0')
                else:
                    print('❌ 触发器未按预期恢复 seat_bitmap，请检查触发器定义')
            else:
                print('未找到对应 seat_status 记录')
    finally:
        conn.close()


if __name__ == '__main__':
    verify()
