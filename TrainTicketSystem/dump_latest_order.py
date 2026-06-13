"""
dump_latest_order.py

导出最近一笔订单的全部字段，用于调试。
"""
from utils.db_helper import get_connection
import pymysql


def dump():
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                'SELECT * FROM orders ORDER BY create_time DESC LIMIT 1'
            )
            o = cursor.fetchone()
            print('Latest order:', o)
    finally:
        conn.close()


if __name__ == '__main__':
    dump()
