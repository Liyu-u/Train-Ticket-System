"""
db_config.py

从环境变量加载数据库配置信息，优先使用 `.env` 文件（由 python-dotenv 加载）。

环境变量（可选默认值）：
 - DB_HOST (默认 127.0.0.1)
 - DB_PORT (默认 3306)
 - DB_USER (默认 root)
 - DB_PASSWORD (默认 空字符串)
 - DB_NAME (默认 train_ticket)

使用示例：在 PowerShell 中临时设置：
	$env:DB_PASSWORD='your_pass'

注：此配置与现有代码兼容（返回与 pymysql.connect 兼容的字典）。
"""
from dotenv import load_dotenv
import os

load_dotenv()

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'train_ticket')

def get_db_config():
		"""返回用于 `pymysql.connect` 的数据库参数字典。"""
		return {
				'host': DB_HOST,
				'port': DB_PORT,
				'user': DB_USER,
				'password': DB_PASSWORD,
				'database': DB_NAME,
				'autocommit': False,
		}

