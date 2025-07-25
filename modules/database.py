import os
import hashlib
import logging
import psycopg2
from datetime import datetime
from urllib.parse import urlparse
from modules.constants import DATABASE_URL, STATUS

logger = logging.getLogger(__name__)

def execute_query(query, params=(), fetch=False, return_cursor=False):
    try:
        url = urlparse(DATABASE_URL)
        
        # 检查是否是PostgreSQL URL
        if url.scheme != 'postgresql' and url.scheme != 'postgres':
            raise ValueError(f"不支持的数据库类型: {url.scheme}，请使用PostgreSQL")
        
        # 解析PostgreSQL连接参数
        dbname = url.path[1:] if url.path else 'postgres'
        user = url.username
        password = url.password
        host = url.hostname or 'localhost'
        port = url.port or 5432
        
        # 构建连接参数
        conn_params = {
            'dbname': dbname,
            'user': user,
            'password': password,
            'host': host,
            'port': port
        }
        
        # 移除None值
        conn_params = {k: v for k, v in conn_params.items() if v is not None}
        
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()
        query = query.replace('?', '%s')
        cursor.execute(query, params)
        if return_cursor:
            conn.commit()
            return cursor
        result = None
        if fetch:
            result = cursor.fetchall()
        conn.commit()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"数据库查询失败: {str(e)}")
        raise e

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_all_sellers():
    return execute_query("SELECT telegram_id, username, first_name, nickname, is_active FROM sellers ORDER BY added_at DESC", fetch=True)

def get_active_seller_ids():
    sellers = execute_query("SELECT telegram_id FROM sellers WHERE is_active = TRUE", fetch=True)
    return [seller[0] for seller in sellers] if sellers else []

def get_seller_info(telegram_id):
    result = execute_query("SELECT telegram_id, nickname, username, first_name, is_active FROM sellers WHERE telegram_id = %s", (telegram_id,), fetch=True)
    if not result:
        return None
    seller = result[0]
    telegram_id, nickname, username, first_name, is_active = seller
    display_name = nickname or first_name or f"Seller {telegram_id}"
    return {"telegram_id": telegram_id, "nickname": nickname, "username": username, "first_name": first_name, "display_name": display_name, "is_active": bool(is_active)}

def add_seller(telegram_id, username, first_name, nickname, added_by):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute_query("INSERT INTO sellers (telegram_id, username, first_name, nickname, added_at, added_by) VALUES (%s, %s, %s, %s, %s, %s)", (telegram_id, username, first_name, nickname, timestamp, added_by))

def toggle_seller_status(telegram_id):
    execute_query("UPDATE sellers SET is_active = NOT is_active WHERE telegram_id = %s", (telegram_id,))

def remove_seller(telegram_id):
    return execute_query("DELETE FROM sellers WHERE telegram_id=%s", (telegram_id,))

def update_seller_nickname(telegram_id, nickname):
    execute_query("UPDATE sellers SET nickname = %s WHERE telegram_id = %s", (nickname, telegram_id))

def update_seller_last_active(telegram_id):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute_query("UPDATE sellers SET last_active_at = %s WHERE telegram_id = %s", (timestamp, telegram_id))

def update_seller_info(telegram_id, username=None, first_name=None):
    fields_to_update = []
    params = []
    placeholder = "%s"
    if username is not None:
        fields_to_update.append(f"username = {placeholder}")
        params.append(username)
    if first_name is not None:
        fields_to_update.append(f"first_name = {placeholder}")
        params.append(first_name)
    if not fields_to_update:
        return
    params.append(telegram_id)
    sql = f"UPDATE sellers SET {', '.join(fields_to_update)} WHERE telegram_id = {placeholder}"
    execute_query(sql, params)

def create_order_with_deduction_atomic(account, password, package, remark, username, user_id):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execute_query(
            "INSERT INTO orders (account, password, package, status, created_at, remark, user_id, web_user_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (account, password, package, 'submitted', now, remark, user_id, username)
        )
        return True, "订单创建成功", 0, 0
    except Exception as e:
        logger.error(f"创建订单失败: {str(e)}", exc_info=True)
        return False, f"创建订单失败: {str(e)}", None, None

def check_db_connection():
    """检查数据库连接"""
    try:
        execute_query("SELECT 1")
        logger.info("数据库连接正常")
        return True
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}")
        return False

def init_db():
    """初始化数据库表"""
    try:
        # 创建用户表
        execute_query("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                email VARCHAR(100),
                role VARCHAR(20) DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        
        # 创建卖家表
        execute_query("""
            CREATE TABLE IF NOT EXISTS sellers (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(50),
                first_name VARCHAR(50),
                nickname VARCHAR(50),
                is_active BOOLEAN DEFAULT TRUE,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                added_by VARCHAR(50),
                last_active_at TIMESTAMP
            )
        """)
        
        # 创建订单表
        execute_query("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                account VARCHAR(255) NOT NULL,
                password VARCHAR(255),
                package VARCHAR(10) NOT NULL,
                status VARCHAR(20) DEFAULT 'submitted',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                accepted_at TIMESTAMP,
                completed_at TIMESTAMP,
                accepted_by VARCHAR(50),
                remark TEXT,
                user_id INTEGER REFERENCES users(id),
                web_user_id VARCHAR(50)
            )
        """)
        
        # 创建默认管理员用户（如果不存在）
        admin_password = hash_password('admin123')
        execute_query("""
            INSERT INTO users (username, password, email, role) 
            VALUES ('admin', %s, 'admin@example.com', 'admin') 
            ON CONFLICT (username) DO NOTHING
        """, (admin_password,))
        
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise
