"""
order_service.py

核心购票服务：提供高并发安全的购票事务。

技术要点（答辩用）：
1. SELECT ... FOR UPDATE 获取目标座位行的排他锁（悲观锁）
2. 按位与 (&) 检测区间冲突：`if (seat_bitmap & buy_mask) != 0` → 拒绝
3. 按位或 (|) 更新占用位图：`new_bitmap = seat_bitmap | buy_mask`
4. 同时写入 order_status='PAID' 和 status=1（双写，确保触发器与视图正常工作）
5. 任何异常均回滚，保证库存与订单的一致性
"""
import uuid
from utils.db_helper import get_connection


def buy_ticket(user_id, train_id, carriage_no, seat_no, buy_mask):
    """在事务内完成一次高并发安全的购票请求。

    参数：
        user_id     -- 购票用户 ID
        train_id    -- 车次编号（如 'G101'）
        carriage_no -- 车厢号（整型）
        seat_no     -- 座位号（如 '01A'）
        buy_mask    -- 请求区间的二进制掩码（整型）

    返回：
        成功时返回订单号 (str)，失败时返回 None。
    """
    conn = get_connection(autocommit=False)
    try:
        with conn.cursor() as cursor:
            # 1) SELECT ... FOR UPDATE：锁定目标座位行，阻止并发写入
            cursor.execute(
                """SELECT seat_id, seat_bitmap
                   FROM seat_status
                   WHERE train_id = %s AND carriage_no = %s AND seat_no = %s
                   FOR UPDATE""",
                (train_id, carriage_no, seat_no)
            )
            seat = cursor.fetchone()

            if not seat:
                conn.rollback()
                print(f"[{user_id}] 购票失败：未找到座位 {train_id} {carriage_no}-{seat_no}")
                return None

            seat_id = seat[0]
            current_bitmap = seat[1] or 0

            # 2) 按位与冲突检测：任何一位重叠即拒绝
            if (current_bitmap & buy_mask) != 0:
                conn.rollback()
                print(f"[{user_id}] 购票失败：区间冲突（seat_id={seat_id}，"
                      f"当前位图={bin(current_bitmap)}，请求掩码={bin(buy_mask)}）")
                return None

            # 3) 无冲突 → 按位或更新位图
            new_bitmap = current_bitmap | buy_mask
            cursor.execute(
                "UPDATE seat_status SET seat_bitmap = %s WHERE seat_id = %s",
                (new_bitmap, seat_id)
            )

            # 4) 生成订单（双写 order_status + status）
            order_id = 'ORD' + uuid.uuid4().hex[:10].upper()
            cursor.execute(
                """INSERT INTO orders
                   (order_id, user_id, train_id, seat_id, buy_mask, order_status, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (order_id, user_id, train_id, seat_id, buy_mask, 'PAID', 1)
            )

            # 5) 提交事务，释放行锁
            conn.commit()
            print(f"[{user_id}] 购票成功，订单号: {order_id}，"
                  f"已锁定位图: {bin(buy_mask)}")
            return order_id

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[{user_id}] 系统异常，事务已回滚：{e}")
        return None
    finally:
        conn.close()
