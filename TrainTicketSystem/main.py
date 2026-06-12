# main.py
# 项目入口（控制台交互）。
#
# 包含：
# - 简易登录（ADMIN / USER）
# - 查询座位列表与余票展示
# - 高并发抢票实现：`buy_ticket()`（事务 + SELECT ... FOR UPDATE + 位运算冲突检测 + 回滚）
#
# 说明：为答辩展示，注释详尽，且使用环境变量优先的数据库配置（避免明文硬编码）。
"""
main.py
项目入口（控制台交互）。

包含：
- 简易登录（ADMIN / USER）
- 查询座位列表与余票展示
- 高并发抢票实现：`buy_ticket()`（事务 + SELECT ... FOR UPDATE + 位运算冲突检测 + 回滚）

说明：为答辩展示，注释详尽，且使用环境变量优先的数据库配置（避免明文硬编码）。
"""
import os
import uuid
import pymysql
from getpass import getpass


def get_db_conn():
	"""返回一个未自动提交的 pymysql 连接。

	优先使用环境变量：`DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`。
	目的是在演示/部署时避免明文凭据出现在代码中。
	"""
	host = os.getenv('DB_HOST', '127.0.0.1')
	user = os.getenv('DB_USER', 'root')
	password = os.getenv('DB_PASSWORD', '')
	db = os.getenv('DB_NAME', 'train_ticket')
	return pymysql.connect(host=host, user=user, password=password, database=db, autocommit=False)


def buy_ticket(user_id, train_id, carriage_no, seat_no, buy_mask):
	"""在事务内完成一次购票请求（示范用）

	核心步骤及要点（答辩用注释）：
	1) 建立连接并关闭自动提交，由调用方或函数手动提交/回滚，保证事务边界明确。
	2) 使用 `SELECT ... FOR UPDATE` 获取目标座位行的排他锁，阻止并发写入。
	3) 使用按位与检测冲突：`if (seat_bitmap & buy_mask) != 0` 表示有重叠区间，拒绝购票。
	4) 使用按位或更新占用位图：`new_bitmap = seat_bitmap | buy_mask`，并写回数据库。
	5) 插入订单记录，最后提交事务并返回订单号。

	参数：
	- `user_id`：当前发起购票的用户 ID
	- `train_id`：车次
	- `carriage_no`：车厢号（整型）
	- `seat_no`：座位号（字符串，如 '01A'）
	- `buy_mask`：整型掩码，表示所请求区间的二进制位（答辩时演示如何构建）
	"""
	conn = get_db_conn()
	try:
		with conn.cursor(pymysql.cursors.DictCursor) as cursor:
			# 1) 锁定目标座位行，使用 FOR UPDATE 获取行级排他锁（悲观锁）
			sql_lock = '''
				SELECT seat_id, seat_bitmap
				FROM seat_status
				WHERE train_id = %s AND carriage_no = %s AND seat_no = %s
				FOR UPDATE
			'''
			cursor.execute(sql_lock, (train_id, carriage_no, seat_no))
			seat = cursor.fetchone()

			if not seat:
				# 座位不存在 -> 回滚并返回失败
				conn.rollback()
				print(f"[{user_id}] ❌ 指定座位未找到：{train_id} {carriage_no}-{seat_no}")
				return None

			current_bitmap = seat['seat_bitmap'] or 0

			# 2) 按位与检测冲突：任何一位被占用都表明区间冲突
			if (current_bitmap & buy_mask) != 0:
				# 冲突，立即回滚并返回
				conn.rollback()
				print(f"[{user_id}] ❌ 购票失败：选定区间与已售区间冲突（seat_id={seat['seat_id']}）。")
				return None

			# 3) 无冲突 -> 执行按位或更新，原子性依赖于事务与行锁
			new_bitmap = current_bitmap | buy_mask
			sql_update = "UPDATE seat_status SET seat_bitmap = %s WHERE seat_id = %s"
			cursor.execute(sql_update, (new_bitmap, seat['seat_id']))

			# 4) 生成订单流水，演示使用简短可读的订单号（答辩友好）
			order_id = 'ORD' + uuid.uuid4().hex[:10].upper()
			sql_order = '''
				INSERT INTO orders (order_id, user_id, train_id, seat_id, buy_mask, order_status)
				VALUES (%s, %s, %s, %s, %s, %s)
			'''
			cursor.execute(sql_order, (order_id, user_id, train_id, seat['seat_id'], buy_mask, 'PAID'))

			# 5) 提交事务，释放行锁
			conn.commit()
			print(f"[{user_id}] ✅ 购票成功，订单号: {order_id}，已锁定位图: {bin(buy_mask)}")
			return order_id

	except Exception as e:
		# 任何异常都应当回滚，保证库存与订单的一致性
		try:
			conn.rollback()
		except Exception:
			pass
		print(f"[{user_id}] ⚠️ 系统异常，事务已回滚：{e}")
		return None
	finally:
		conn.close()


def prompt_mask_from_binary_str(bin_str: str) -> int:
	"""辅助：从用户输入的二进制字符串（如 '00110'）生成掩码整数。

	在答辩时可以演示：每一位代表相邻站段是否被占用，右侧最低位对应第 0 段。
	"""
	s = bin_str.strip()
	if not s:
		return 0
	# 允许用户输入 '0b101' 或 '101'
	if s.startswith('0b'):
		s = s[2:]
	return int(s, 2)


def simple_login():
	"""演示用的简易登录：用户名 + 密码 -> 返回 user_id 与 role_type（默认 user_id=username）。

	注：真实项目请使用密码哈希与安全认证机制，此处为答辩演示简化实现。
	"""
	username = input('用户名: ').strip()
	password = getpass('密码: ')

	# 直接查询 users 表以获取 role_type
	conn = get_db_conn()
	try:
		with conn.cursor(pymysql.cursors.DictCursor) as cursor:
			cursor.execute('SELECT user_id, role_type FROM users WHERE username=%s AND password=%s', (username, password))
			u = cursor.fetchone()
			if not u:
				print('登录失败：用户名或密码错误')
				return None, None
			print(f"登录成功：{username}（{u['role_type']}）")
			return u['user_id'], u['role_type']
	finally:
		conn.close()


def show_seats(train_id):
	"""展示指定车次的座位与当前位图状态（方便在演示时观察库存变化）。"""
	conn = get_db_conn()
	try:
		with conn.cursor(pymysql.cursors.DictCursor) as cursor:
			cursor.execute('SELECT seat_id, carriage_no, seat_no, seat_bitmap FROM seat_status WHERE train_id=%s', (train_id,))
			rows = cursor.fetchall()
			if not rows:
				print('未找到该车次的座位信息')
				return
			print('seat_id | carriage | seat_no | seat_bitmap (binary)')
			for r in rows:
				print(f"{r['seat_id']:7d} | {r['carriage_no']:7d} | {r['seat_no']:6s} | {bin(r['seat_bitmap'])}")
	finally:
		conn.close()


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
			print('管理员视图示例：查询视图 v_daily_financial_report（如已创建）')
			conn = get_db_conn()
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
