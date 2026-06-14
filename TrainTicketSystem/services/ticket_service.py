"""
ticket_service.py

票务查询服务：提供车次查询、座位查询等只读操作。
"""
from utils.db_helper import get_connection


def query_trains():
    """返回所有车次信息列表（V3.1: 计价熔断 — 管理员自定义 > 前缀自动定价）。

    返回字段：
        train_id, train_no, departure, arrival, departure_time, total_seats, base_rate

    base_rate 取值逻辑（与 /api/buy 完全一致）：
        COALESCE(NULLIF(t.price, 0), tm.base_rate, 100.00)
          → t.price > 0 ？用管理员自定义价
          → t.price = 0 ？用 train_models 前缀自动定价
          → 都没有      ？兜底 100.00
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT
                       t.train_id,
                       t.train_no,
                       t.departure,
                       t.arrival,
                       t.departure_time,
                       t.total_seats,
                       COALESCE(NULLIF(t.price, 0), tm.base_rate, 100.00) AS base_rate
                   FROM train_info t
                   LEFT JOIN train_models tm ON tm.type_code = LEFT(t.train_id, 1)
                   ORDER BY t.train_id"""
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def query_seats(train_id):
    """查询指定车次的所有座位及 V3.1 动态计价信息（含管理员自定义定价熔断）。

    参数：
        train_id -- 车次编号（如 'G101'）

    返回：
        list[dict] — 包含 seat_id, carriage_no, seat_no, seat_bitmap, default_mask,
                     class_code, class_name, price_multiplier, base_rate。

    base_rate 取值逻辑（与 /api/buy、/api/query_routes 完全一致）：
        COALESCE(NULLIF(ti.price, 0), tm.base_rate, 100.00)
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT
                       s.seat_id,
                       s.carriage_no,
                       s.seat_no,
                       s.seat_bitmap,
                       s.default_mask,
                       s.class_code,
                       COALESCE(sc.class_name, '二等座')       AS class_name,
                       COALESCE(sc.price_multiplier, 1.0)      AS price_multiplier,
                       COALESCE(NULLIF(ti.price, 0), tm.base_rate, 100.00) AS base_rate
                   FROM seat_status s
                   LEFT JOIN seat_classes sc ON s.class_code = sc.class_code
                   JOIN train_info ti ON ti.train_id = s.train_id
                   LEFT JOIN train_models tm ON tm.type_code = LEFT(ti.train_id, 1)
                   WHERE s.train_id = %s
                   ORDER BY s.carriage_no, s.seat_no""",
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
