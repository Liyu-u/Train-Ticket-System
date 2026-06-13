"""
ticket_service.py

票务查询服务：提供车次查询、座位查询等只读操作。
"""
from utils.db_helper import get_connection


def query_trains():
    """返回所有车次信息列表。

    返回字段：
        train_id, train_no, departure, arrival, departure_time, price, total_seats

    返回：
        list[dict] — 按 train_id 升序排列的车次列表。
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT train_id, train_no, departure, arrival,
                          departure_time, price, total_seats
                   FROM train_info
                   ORDER BY train_id"""
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def query_seats(train_id):
    """查询指定车次的所有座位及当前位图状态。

    参数：
        train_id -- 车次编号（如 'G101'）

    返回：
        list[dict] — 包含 seat_id, carriage_no, seat_no, seat_bitmap, default_mask。
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT seat_id, carriage_no, seat_no, seat_bitmap, default_mask
                   FROM seat_status
                   WHERE train_id = %s
                   ORDER BY carriage_no, seat_no""",
                (train_id,)
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def query_seat_by_id(seat_id):
    """按 seat_id 查询单个座位信息。

    返回：
        dict 或 None。
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT seat_id, train_id, carriage_no, seat_no,
                          seat_bitmap, default_mask
                   FROM seat_status
                   WHERE seat_id = %s""",
                (seat_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))
    finally:
        conn.close()
