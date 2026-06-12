import os
import pymysql

def get_conn():
    host = os.getenv('DB_HOST', '127.0.0.1')
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    db = os.getenv('DB_NAME', 'train_ticket')
    return pymysql.connect(host=host, user=user, password=password, database=db, autocommit=True)

def dump():
    conn = get_conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute('SELECT * FROM orders ORDER BY create_time DESC LIMIT 1')
            o = cursor.fetchone()
            print('Latest order:', o)
    finally:
        conn.close()

if __name__ == '__main__':
    dump()
