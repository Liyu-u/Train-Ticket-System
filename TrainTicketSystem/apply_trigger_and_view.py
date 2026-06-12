"""
apply_trigger_and_view.py

通过 PyMySQL 直接在数据库中创建单语句触发器并创建/替换财务视图。
此脚本直接执行字符串 SQL，避免 DELIMITER 相关问题。
"""
import os
import pymysql


def get_conn():
    host = os.getenv('DB_HOST', '127.0.0.1')
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    db = os.getenv('DB_NAME', 'train_ticket')
    port = int(os.getenv('DB_PORT', 3306))
    return pymysql.connect(host='127.0.0.1', user='root', password='135246', database=db, port=port, autocommit=True)

def apply_trigger_and_view():
    # 单行触发器 SQL（与 sql_scripts/03_refund_trigger.sql 保持一致）
    trigger_sql = (
        "DROP TRIGGER IF EXISTS trg_orders_after_update_refund;"
        "CREATE TRIGGER trg_orders_after_update_refund "
        "AFTER UPDATE ON orders "
        "FOR EACH ROW "
        "UPDATE seat_status SET seat_bitmap = seat_bitmap & (~ NEW.buy_mask) "
        "WHERE seat_id = NEW.seat_id AND NEW.status = 2 AND (OLD.status IS NULL OR OLD.status != 2);"
    )

    # 读取视图 SQL 文件并作为单条语句执行（该文件已使用单个 CREATE VIEW 语句）
    view_path = os.path.join(os.path.dirname(__file__), 'sql_scripts', '04_financial_view.sql')
    with open(view_path, 'r', encoding='utf-8') as f:
        view_sql = f.read()

    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            print('Applying trigger...')
            try:
                # 有些驱动不允许一次执行多条语句，因此先尝试拆分并逐条执行
                for stmt in [s.strip() for s in trigger_sql.split(';') if s.strip()]:
                    cursor.execute(stmt + ';')
                print('Trigger applied successfully')
            except Exception as e:
                print('Trigger application failed:', e)
                raise

            print('Applying view...')
            try:
                # 视图脚本通常包含 DROP VIEW IF EXISTS; CREATE VIEW ...; 我们按分号拆分并执行每一条
                statements = [s.strip() for s in view_sql.split(';') if s.strip()]
                for stmt in statements:
                    cursor.execute(stmt + ';')
                print('View applied successfully')
            except Exception as e:
                print('View application failed:', e)
                raise
    finally:
        conn.close()


if __name__ == '__main__':
    apply_trigger_and_view()
