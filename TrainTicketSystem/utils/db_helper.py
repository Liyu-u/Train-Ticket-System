"""
db_helper.py

数据库连接公共入口模块。

全项目所有需要数据库连接的模块统一从此处导入 `get_connection`，
不再各自重复定义 get_db_conn() / get_conn()。

使用示例：
    from utils.db_helper import get_connection

    conn = get_connection()           # 手动管理事务
    conn = get_connection(autocommit=True)  # 自动提交
"""

# 从 config.db_config 导入连接工厂并重导出
from config.db_config import get_connection  # noqa: F401
