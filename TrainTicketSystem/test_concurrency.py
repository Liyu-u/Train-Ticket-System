"""
test_concurrency.py

并发测试脚本（多线程），用于验证 `buy_ticket()` 在高并发冲突下的悲观锁与事务回滚行为。

主要行为：
- 在同一瞬间发起 N 个并发线程（默认 50），所有线程尝试抢购完全相同的资源：
  train_id='G101', carriage_no=1, seat_no='01A', buy_mask=0b11
- 高表现力日志：每个线程打印结构化日志（包含线程号）。
- 汇总结果并断言：成功次数必须为 1，失败次数为 N-1。

运行前请确保：
1) 已在目标 MySQL 中执行建表脚本，创建库 `train_ticket` 及表。
2) 确保 `seat_status` 中存在目标座位：train_id='G101', carriage_no=1, seat_no='01A'，
   且 `seat_bitmap=0`（未售）。
3) 在环境变量中设置数据库连接信息（或在 .env 文件中配置）：
   DB_HOST, DB_USER, DB_PASSWORD, DB_NAME （默认 DB_NAME=train_ticket）

示例运行：
    pip install pymysql python-dotenv
    python TrainTicketSystem/test_concurrency.py

注意：脚本会在运行前重置目标座位的 `seat_bitmap` 为 0 并删除该 seat_id 的 orders（谨慎执行）。
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import time

from services.order_service import buy_ticket
from utils.db_helper import get_connection


# 测试配置
NUM_THREADS = 50
TRAIN_ID = 'G101'
CARRIAGE_NO = 1
SEAT_NO = '01A'
BUY_MASK = 0b11  # 示例区间掩码（两段）


def pre_test_setup():
    """预置：确保目标座位存在，重置 seat_bitmap 并删除相关订单（测试隔离）。"""
    conn = get_connection(autocommit=False)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT seat_id FROM seat_status
                   WHERE train_id = %s AND carriage_no = %s AND seat_no = %s""",
                (TRAIN_ID, CARRIAGE_NO, SEAT_NO)
            )
            row = cursor.fetchone()
            if not row:
                print(f"目标座位不存在，请先插入：{TRAIN_ID} {CARRIAGE_NO} {SEAT_NO}")
                conn.close()
                sys.exit(2)
            seat_id = row[0]

            cursor.execute(
                "UPDATE seat_status SET seat_bitmap = 0 WHERE seat_id = %s",
                (seat_id,)
            )
            cursor.execute(
                "DELETE FROM orders WHERE seat_id = %s",
                (seat_id,)
            )
            conn.commit()
            print(f"[预置] seat_id={seat_id} 已重置：seat_bitmap=0，并删除相关订单。")
            return seat_id
    finally:
        conn.close()


def worker(thread_idx, start_event, results, lock, seat_id):
    label = f"线程-{thread_idx:02d}"
    start_event.wait()
    print(f"[{label}] 正在发起锁定请求...")
    try:
        user_id = f"UT{thread_idx:03d}"
        order_id = buy_ticket(user_id, TRAIN_ID, CARRIAGE_NO, SEAT_NO, BUY_MASK)
        if order_id:
            print(f"[{label}] ✅ 抢票成功！已锁定座位并生成订单: {order_id}")
            with lock:
                results.append(True)
        else:
            print(f"[{label}] ❌ 抢票失败：排他锁互斥或区间已被占用，事务已回滚。")
            with lock:
                results.append(False)
    except Exception as e:
        print(f"[{label}] ⚠️ 异常发生：{e}")
        with lock:
            results.append(False)


def main():
    print(f"启动并发测试：{NUM_THREADS} 个线程同时请求同一座位 "
          f"{TRAIN_ID} {CARRIAGE_NO}-{SEAT_NO}（掩码 {bin(BUY_MASK)}）")

    seat_id = pre_test_setup()

    start_event = threading.Event()
    lock = threading.Lock()
    results = []

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [
            executor.submit(worker, i + 1, start_event, results, lock, seat_id)
            for i in range(NUM_THREADS)
        ]

        time.sleep(0.5)
        print("所有线程就绪，3..2..1，开始！")
        start_event.set()

        for fut in as_completed(futures):
            pass

    success_count = sum(1 for r in results if r)
    failure_count = sum(1 for r in results if not r)

    print('\n====== 测试汇总 ======')
    print(f'总线程数: {NUM_THREADS}')
    print(f'成功次数: {success_count}')
    print(f'失败次数: {failure_count}')

    try:
        assert success_count == 1 and failure_count == (NUM_THREADS - 1), (
            '并发结果不符合预期：成功次数应为 1，失败次数应为 N-1。')
        print('断言通过：只有 1 个线程成功，其余均失败（悲观锁与事务回滚生效）。')
        sys.exit(0)
    except AssertionError as e:
        print('断言失败：', e)
        sys.exit(3)


if __name__ == '__main__':
    main()
