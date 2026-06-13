"""
apply_trigger_and_view.py

通过 PyMySQL 直接在数据库中创建单语句触发器并创建/替换财务视图。
使用环境变量配置数据库连接（不再硬编码密码）。
"""
import os
from utils.db_helper import get_connection


def apply_trigger_and_view():
    """应用退票触发器与财务日报视图。"""
    # 单行触发器 SQL（与 sql_scripts/03_refund_trigger.sql 保持一致）
    trigger_sql = (
        "DROP TRIGGER IF EXISTS trg_orders_after_update_refund;"
        "CREATE TRIGGER trg_orders_after_update_refund "
        "AFTER UPDATE ON orders "
        "FOR EACH ROW "
        "UPDATE seat_status SET seat_bitmap = seat_bitmap & (~ NEW.buy_mask) "
        "WHERE seat_id = NEW.seat_id AND NEW.status = 2 "
        "AND (OLD.status IS NULL OR OLD.status != 2);"
    )

    # 读取视图 SQL 文件
    view_path = os.path.join(
        os.path.dirname(__file__), 'sql_scripts', '04_financial_view.sql'
    )
    with open(view_path, 'r', encoding='utf-8') as f:
        view_sql = f.read()

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cursor:
            print('Applying trigger...')
            try:
                for stmt in [s.strip() for s in trigger_sql.split(';') if s.strip()]:
                    cursor.execute(stmt + ';')
                print('Trigger applied successfully')
            except Exception as e:
                print('Trigger application failed:', e)
                raise

            print('Applying view...')
            try:
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
