"""
db_setup.py

数据库预置脚本（幂等）：
- 确保包含示例车次 G101, G102, G103
- 为每个车次插入 5 个示例座位（1-01A, 1-01B, 1-02A, 1-02B, 1-03A）
- 为每个座位写入默认掩码（default_mask）: 0b00001,0b00010,0b00100,0b01000,0b10000
- 初始化 seat_bitmap=0

同时包含 `reset_all_data()` 用于一键重置样例数据（CLI 支持 `--reset`）。
"""

import os
import pymysql
import argparse
from dotenv import load_dotenv
load_dotenv()

def get_db_conn(autocommit=True):
    host = os.getenv('DB_HOST', '127.0.0.1')
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    db = os.getenv('DB_NAME', 'train_ticket')
    return pymysql.connect(host=host, user=user, password=password, database=db, autocommit=autocommit)


def ensure_tables():
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            # 创建 train_info（如果不存在）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS train_info (
                    train_id VARCHAR(20) PRIMARY KEY,
                    train_no VARCHAR(20),
                    departure VARCHAR(100),
                    arrival VARCHAR(100),
                    departure_time DATETIME,
                    price DECIMAL(10,2),
                    total_seats INT
                ) ENGINE=InnoDB;
            ''')

            # 创建 seat_status（如果不存在），并增加 default_mask 列用于示例映射
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS seat_status (
                    seat_id INT AUTO_INCREMENT PRIMARY KEY,
                    train_id VARCHAR(20) NOT NULL,
                    carriage_no INT NOT NULL,
                    seat_no VARCHAR(10) NOT NULL,
                    seat_bitmap INT DEFAULT 0,
                    default_mask INT DEFAULT 0,
                    UNIQUE KEY uk_train_seat (train_id, carriage_no, seat_no)
                ) ENGINE=InnoDB;
            ''')

            # 如旧表缺少新列，尝试添加（幂等）
            try:
                cursor.execute('ALTER TABLE seat_status ADD COLUMN IF NOT EXISTS default_mask INT DEFAULT 0')
            except Exception:
                pass

            # 创建 orders 表（如果不存在，简单示例 schema，用于演示）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    order_id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64),
                    train_id VARCHAR(20),
                    seat_id INT,
                    buy_mask INT DEFAULT 0,
                    price DECIMAL(10,2) DEFAULT 0,
                    -- 双写兼容：部分代码使用字符串型 order_status，有的使用整型 status
                    order_status VARCHAR(20) DEFAULT 'PAID',
                    status INT DEFAULT 1,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')
            # 确保兼容列存在
            try:
                cursor.execute('ALTER TABLE orders ADD COLUMN IF NOT EXISTS buy_mask INT DEFAULT 0')
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_status VARCHAR(20) DEFAULT 'PAID'")
            except Exception:
                pass
            try:
                cursor.execute('ALTER TABLE orders ADD COLUMN IF NOT EXISTS status INT DEFAULT 1')
            except Exception:
                pass
            try:
                cursor.execute('ALTER TABLE train_info ADD COLUMN IF NOT EXISTS train_no VARCHAR(20)')
            except Exception:
                pass
            try:
                cursor.execute('ALTER TABLE train_info ADD COLUMN IF NOT EXISTS price DECIMAL(10,2)')
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


def insert_train_if_not_exists(train_id, train_no, departure, arrival, departure_time, price, total_seats=100):
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            # 确保 train_info 表包含需要的列（向后兼容旧表结构）
            try:
                cursor.execute('ALTER TABLE train_info ADD COLUMN IF NOT EXISTS train_no VARCHAR(20)')
            except Exception:
                pass
            try:
                cursor.execute('ALTER TABLE train_info ADD COLUMN IF NOT EXISTS price DECIMAL(10,2)')
            except Exception:
                pass

            cursor.execute('SELECT 1 FROM train_info WHERE train_id=%s LIMIT 1', (train_id,))
            if not cursor.fetchone():
                cursor.execute(
                    'INSERT INTO train_info (train_id, train_no, departure, arrival, departure_time, price, total_seats) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (train_id, train_no, departure, arrival, departure_time, price, total_seats)
                )
                conn.commit()
                print(f'已插入车次 {train_id}')
            else:
                print(f'车次 {train_id} 已存在，跳过创建')
    finally:
        conn.close()


def insert_seat_if_not_exists(train_id, carriage_no, seat_no, default_mask=0):
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT seat_id FROM seat_status WHERE train_id=%s AND carriage_no=%s AND seat_no=%s', (train_id, carriage_no, seat_no))
            if not cursor.fetchone():
                cursor.execute('INSERT INTO seat_status (train_id, carriage_no, seat_no, seat_bitmap, default_mask) VALUES (%s,%s,%s,0,%s)', (train_id, carriage_no, seat_no, default_mask))
                conn.commit()
                print(f'已插入座位 {train_id} {carriage_no} {seat_no} mask={bin(default_mask)}')
            else:
                # 如果存在，确保 seat_bitmap 为 0 并更新 default_mask
                cursor.execute('UPDATE seat_status SET seat_bitmap=0, default_mask=%s WHERE train_id=%s AND carriage_no=%s AND seat_no=%s', (default_mask, train_id, carriage_no, seat_no))
                conn.commit()
                print(f'座位 {train_id} {carriage_no} {seat_no} 已存在，已重置 seat_bitmap=0 并设置 default_mask={bin(default_mask)}')
    finally:
        conn.close()


def reset_all_data():
    """彻底重建示例数据（删除旧数据并重新插入）。"""
    conn = get_db_conn()
    try:
        with conn.cursor() as cursor:
            # 为避免旧表结构与当前脚本冲突，先 drop 表再重建
            cursor.execute('DROP TABLE IF EXISTS orders')
            cursor.execute('DROP TABLE IF EXISTS seat_status')
            cursor.execute('DROP TABLE IF EXISTS train_info')
        conn.commit()
        print('已 DROP orders, seat_status, train_info 表（重建中）')
        # 重新创建基础示例数据
        ensure_tables()
        populate_sample_data()
    finally:
        conn.close()


def populate_sample_data():
    # 三个示例车次
    trains = [
        ('G101', 'G101', '北京南', '上海虹桥', '2026-07-01 08:00:00', 300.00),
        ('G102', 'G102', '上海虹桥', '北京南', '2026-07-01 13:00:00', 300.00),
        ('G103', 'G103', '北京南', '杭州东', '2026-07-01 09:00:00', 180.00),
    ]

    seats = ['01A', '01B', '02A', '02B', '03A']
    masks = [0b00001, 0b00010, 0b00100, 0b01000, 0b10000]

    for t in trains:
        insert_train_if_not_exists(t[0], t[1], t[2], t[3], t[4], t[5])
        for seat_no, mask in zip(seats, masks):
            insert_seat_if_not_exists(t[0], 1, seat_no, mask)


def ensure_sample_data():
    ensure_tables()
    populate_sample_data()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='DB setup for TrainTicketSystem')
    parser.add_argument('--reset', action='store_true', help='Reset all sample data (delete and re-create)')
    args = parser.parse_args()

    if args.reset:
        ensure_tables()
        reset_all_data()
    else:
        ensure_sample_data()

