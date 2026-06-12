"""
apply_sql_via_pymysql.py

尝试通过 PyMySQL 在不依赖 mysql CLI 的情况下应用 SQL 脚本（触发器/视图）。

注意：对于包含自定义分隔符（DELIMITER）的触发器脚本，脚本会去除 DELIMITER 语句并替换自定义分隔符标记（例如 $$）为 ';'，
然后尝试将整个 CREATE TRIGGER 语句一次性提交给数据库。
"""
import os
import pymysql


def get_conn():
    host = os.getenv('DB_HOST', '127.0.0.1')
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    db = os.getenv('DB_NAME', 'train_ticket')
    return pymysql.connect(host=host, user=user, password=password, database=db, autocommit=True)


def apply_sql_file(path):
    print('Applying', path)
    with open(path, 'r', encoding='utf-8') as f:
        sql = f.read()

    # 移除 DELIMITER 行并将自定义分隔符替换为 ';'
    lines = []
    delim = None
    for line in sql.splitlines():
        if line.strip().upper().startswith('DELIMITER'):
            # 获取分隔符标记，例如 $$
            parts = line.strip().split()
            if len(parts) >= 2:
                delim = parts[1]
            continue
        lines.append(line)

    cleaned = '\n'.join(lines)
    if delim:
        cleaned = cleaned.replace(delim, ';')

    # 尝试一次性执行清理后的 SQL 内容
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(cleaned)
                print('Applied successfully')
            except Exception as e:
                print('Failed to execute in one shot, error:', e)
                # 作为回退，按分号分割并逐条执行（注意：此方法对触发器可能失败）
                statements = [s.strip() for s in cleaned.split(';') if s.strip()]
                for stmt in statements:
                    try:
                        cursor.execute(stmt)
                    except Exception as e2:
                        print('Statement failed:', stmt[:80], '... error:', e2)
    finally:
        conn.close()


if __name__ == '__main__':
    apply_sql_file('sql_scripts/03_refund_trigger.sql')
    apply_sql_file('sql_scripts/04_financial_view.sql')
