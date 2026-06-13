"""
main.py
项目入口（控制台交互）。

包含：
- 简易登录（ADMIN / USER）
- 查询座位列表与余票展示
- 高并发抢票实现

说明：为答辩展示，注释详尽，且使用环境变量优先的数据库配置（避免明文硬编码）。

所有数据库连接与业务逻辑均委托给 services/ 和 utils/ 模块。
"""
import pymysql
from getpass import getpass

from utils.db_helper import get_connection
from services.order_service import buy_ticket
from services.ticket_service import query_seats



def prompt_mask_from_binary_str(bin_str: str) -> int:
    """辅助：从用户输入的二进制字符串（如 '00110'）生成掩码整数。

    每一位代表相邻站段是否被占用，右侧最低位对应第 0 段。
    """
    s = bin_str.strip()
    if not s:
        return 0
    if s.startswith('0b'):
        s = s[2:]
    return int(s, 2)


def simple_login():
    """演示用的简易登录：用户名 + 密码 -> 返回 user_id 与 role_type。

    注：真实项目请使用密码哈希与安全认证机制，此处为答辩演示简化实现。
    """
    username = input('用户名: ').strip()
    password = getpass('密码: ')

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                'SELECT user_id, role_type FROM users WHERE username=%s AND password=%s',
                (username, password)
            )
            u = cursor.fetchone()
            if not u:
                print('登录失败：用户名或密码错误')
                return None, None
            print(f"登录成功：{username}（{u['role_type']}）")
            return u['user_id'], u['role_type']
    finally:
        conn.close()


def show_seats(train_id):
    """展示指定车次的座位与当前位图状态。"""
    rows = query_seats(train_id)
    if not rows:
        print('未找到该车次的座位信息')
        return
    print('seat_id | carriage | seat_no | seat_bitmap (binary)')
    for r in rows:
        print(f"{r['seat_id']:7d} | {r['carriage_no']:7d} | "
              f"{r['seat_no']:6s} | {bin(r['seat_bitmap'])}")


def main_menu():
    print('--- 火车票演示系统（控制台） ---')
    user_id, role = simple_login()
    if not user_id:
        return

    while True:
        print('\n操作选项：')
        print('1. 查询某车次座位状态')
        print('2. 购票（高并发事务示范）')
        if role == 'ADMIN':
            print('3. 管理员：查看当日售票统计（示例视图）')
        print('0. 退出')
        choice = input('请选择: ').strip()

        if choice == '1':
            train_id = input('输入车次（如 G101）: ').strip()
            show_seats(train_id)

        elif choice == '2':
            train_id = input('车次: ').strip()
            carriage_no = int(input('车厢号 (数字): ').strip())
            seat_no = input('座位号 (如 01A): ').strip()
            print('请用二进制字符串表示要购买的区间掩码（如 00110 表示第2-3段）')
            bin_str = input('掩码二进制 (例如 00110): ').strip()
            buy_mask = prompt_mask_from_binary_str(bin_str)
            print(f'请求掩码整数值: {buy_mask} (二进制: {bin(buy_mask)})')
            buy_ticket(user_id, train_id, carriage_no, seat_no, buy_mask)

        elif choice == '3' and role == 'ADMIN':
            print('管理员视图示例：查询视图 v_daily_financial_report')
            conn = get_connection(autocommit=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT * FROM v_daily_financial_report LIMIT 20')
                    for row in cursor.fetchall():
                        print(row)
            except Exception as e:
                print('查询视图失败（可能尚未创建）：', e)
            finally:
                conn.close()

        elif choice == '0':
            print('退出，感谢演示。')
            break
        else:
            print('无效选项，请重试。')


if __name__ == '__main__':
    main_menu()
