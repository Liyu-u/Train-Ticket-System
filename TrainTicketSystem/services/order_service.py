import pymysql
import uuid

def buy_ticket(user_id, train_id, carriage_no, seat_no, buy_mask):
    """
    核心购票事务：包含排他锁查票、位图防冲突验证、库存扣减与订单生成
    """
    # 1. 建立数据库连接（注意：必须关闭 autocommit，手动接管事务！）
    conn = pymysql.connect(
        host='127.0.0.1', 
        user='root', 
        password='135246', # 记得换成您的本地 MySQL 密码
        database='ticket_system', 
        autocommit=False
    )

    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            print(f"[{user_id}] 正在锁定座位...")

            # 2. 查询座位状态并加上排他锁 (FOR UPDATE)
            sql_lock = """
                SELECT seat_id, seat_bitmap
                FROM seat_status
                WHERE train_id = %s AND carriage_no = %s AND seat_no = %s
                FOR UPDATE;
            """
            cursor.execute(sql_lock, (train_id, carriage_no, seat_no))
            seat = cursor.fetchone()

            if not seat:
                print(f"[{user_id}] ❌ 购票失败：未找到该座位。")
                return False

            # 3. 位图冲突检测（判断目标区间是否被占用）
            # 按位与运算：如果当前状态与请求掩码按位与结果不为 0，说明发生区间重叠
            if (seat['seat_bitmap'] & buy_mask) != 0:
                print(f"[{user_id}] ❌ 购票失败：该区间的车票已被抢走！")
                conn.rollback()
                return False

            # 4. 扣减库存（通过按位或运算，锁定新区间）
            new_bitmap = seat['seat_bitmap'] | buy_mask
            sql_update = "UPDATE seat_status SET seat_bitmap = %s WHERE seat_id = %s"
            cursor.execute(sql_update, (new_bitmap, seat['seat_id']))

            # 5. 生成订单记录
            order_id = "ORD" + str(uuid.uuid4().hex)[:8].upper()
            sql_order = """
                INSERT INTO orders (order_id, user_id, train_id, seat_id, buy_mask)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql_order, (order_id, user_id, train_id, seat['seat_id'], buy_mask))

            # 6. 一切顺利，提交事务，释放行锁！
            conn.commit()
            print(f"[{user_id}] ✅ 购票成功！订单号: {order_id}，已锁定区间: {buy_mask}")
            # ================== 核心炫技点结束 ==================
            return True

    except Exception as e:
        # 发生任何异常，立刻回滚撤销，保证订单和库存绝对不乱
        conn.rollback()
        print(f"[{user_id}] ⚠️ 系统异常，事务已回滚: {e}")
        return False
    finally:
        conn.close()