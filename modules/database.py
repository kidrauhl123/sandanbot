import os
import time
import hashlib
import logging
import psycopg2
from functools import wraps
from datetime import datetime, timedelta
from urllib.parse import urlparse
import pytz
import random

from modules.constants import DATABASE_URL, STATUS, ADMIN_USERNAME, ADMIN_PASSWORD

# 设置日志
logger = logging.getLogger(__name__)

# 中国时区
CN_TIMEZONE = pytz.timezone('Asia/Shanghai')

# 获取中国时间的函数
def get_china_time():
    """获取当前中国时间（UTC+8）"""
    utc_now = datetime.now(pytz.utc)
    china_now = utc_now.astimezone(CN_TIMEZONE)
    return china_now.strftime("%Y-%m-%d %H:%M:%S")

# ===== 数据库 =====
def init_db():
    """初始化数据库"""
    try:
        init_postgres_db()
        # 创建充值相关表
        create_recharge_tables()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}", exc_info=True)



def init_postgres_db():
    """初始化PostgreSQL数据库"""
    url = urlparse(DATABASE_URL)
    dbname = url.path[1:]
    user = url.username
    password = url.password
    host = url.hostname
    port = url.port
    
    logger.info(f"使用PostgreSQL数据库: {host}:{port}/{dbname}")
    logger.info(f"连接PostgreSQL数据库: {host}:{port}/{dbname}")
    
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port
    )
    
    # 使用自动提交模式，避免事务问题
    conn.autocommit = True
    cur = conn.cursor()
    
    # 创建订单表
    cur.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        account TEXT,
        password TEXT,
        package TEXT,
        remark TEXT,
        status TEXT DEFAULT 'submitted',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        user_id INTEGER,
        username TEXT,
        accepted_by TEXT,
        accepted_at TIMESTAMP,
        completed_at TIMESTAMP,
        notified INTEGER DEFAULT 0,
        accepted_by_username TEXT,
        accepted_by_first_name TEXT,
        accepted_by_nickname TEXT,
        failed_at TIMESTAMP,
        fail_reason TEXT,
        buyer_confirmed BOOLEAN DEFAULT FALSE,
        confirm_status TEXT DEFAULT 'pending'
    )
    ''')
    
    # 检查orders表是否需要添加accepted_by_nickname列
    try:
        cur.execute("SELECT accepted_by_nickname FROM orders LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为orders表添加accepted_by_nickname列")
        cur.execute("ALTER TABLE orders ADD COLUMN accepted_by_nickname TEXT")
        conn.commit()
    
    # 检查orders表是否需要添加buyer_confirmed列
    try:
        cur.execute("SELECT buyer_confirmed FROM orders LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为orders表添加buyer_confirmed列")
        cur.execute("ALTER TABLE orders ADD COLUMN buyer_confirmed BOOLEAN DEFAULT FALSE")
        conn.commit()
        
    # 检查orders表是否需要添加confirm_status列
    try:
        cur.execute("SELECT confirm_status FROM orders LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为orders表添加confirm_status列")
        cur.execute("ALTER TABLE orders ADD COLUMN confirm_status TEXT DEFAULT 'pending'")
        conn.commit()
    
    # 创建用户表
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        email TEXT,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT,
        balance REAL DEFAULT 0,
        credit_limit REAL DEFAULT 0
    )
    ''')
    
    # 创建卖家表
    cur.execute('''
    CREATE TABLE IF NOT EXISTS sellers (
        telegram_id TEXT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        nickname TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        added_at TEXT,
        added_by TEXT,
        is_admin BOOLEAN DEFAULT FALSE,
        last_active_at TEXT,
        desired_orders INTEGER DEFAULT 0,
        activity_check_at TEXT,
        distribution_level INTEGER DEFAULT 1,
        max_concurrent_orders INTEGER DEFAULT 5
    )
    ''')
    
    # 检查sellers表是否需要添加新字段
    try:
        cur.execute("SELECT last_active_at FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加last_active_at列")
        cur.execute("ALTER TABLE sellers ADD COLUMN last_active_at TEXT")
        conn.commit()
    
    try:
        cur.execute("SELECT desired_orders FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加desired_orders列")
        cur.execute("ALTER TABLE sellers ADD COLUMN desired_orders INTEGER DEFAULT 0")
        conn.commit()
    
    try:
        cur.execute("SELECT activity_check_at FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加activity_check_at列")
        cur.execute("ALTER TABLE sellers ADD COLUMN activity_check_at TEXT")
        conn.commit()
    
    # 检查sellers表是否需要添加distribution_level列
    try:
        cur.execute("SELECT distribution_level FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加distribution_level列")
        cur.execute("ALTER TABLE sellers ADD COLUMN distribution_level INTEGER DEFAULT 1")
        conn.commit()
    
    # 检查sellers表是否需要添加max_concurrent_orders列
    try:
        cur.execute("SELECT max_concurrent_orders FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加max_concurrent_orders列")
        cur.execute("ALTER TABLE sellers ADD COLUMN max_concurrent_orders INTEGER DEFAULT 5")
        conn.commit()
    
    # 检查sellers表是否需要添加participate_in_distribution列
    try:
        cur.execute("SELECT participate_in_distribution FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加participate_in_distribution列")
        cur.execute("ALTER TABLE sellers ADD COLUMN participate_in_distribution BOOLEAN DEFAULT TRUE")
        conn.commit()
    
    # 检查sellers表是否需要添加nickname列
    try:
        cur.execute("SELECT nickname FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加nickname列")
        cur.execute("ALTER TABLE sellers ADD COLUMN nickname TEXT")
        conn.commit()
    
    # 检查sellers表是否需要添加is_admin列
    try:
        cur.execute("SELECT is_admin FROM sellers LIMIT 1")
    except psycopg2.errors.UndefinedColumn:
        logger.info("为sellers表添加is_admin列")
        cur.execute("ALTER TABLE sellers ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
        conn.commit()
    
    # 创建用户自定义价格表
    cur.execute('''
    CREATE TABLE IF NOT EXISTS user_custom_prices (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        package TEXT NOT NULL,
        price REAL NOT NULL,
        created_at TEXT NOT NULL,
        created_by INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (created_by) REFERENCES users (id),
        UNIQUE(user_id, package)
    )
    ''')
    
    # 创建超级管理员账号（如果不存在）
    admin_hash = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
    cur.execute("SELECT id FROM users WHERE username = %s", (ADMIN_USERNAME,))
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users (username, password_hash, is_admin, created_at) 
            VALUES (%s, %s, 1, %s)
        """, (ADMIN_USERNAME, admin_hash, get_china_time()))
    
    # 创建索引以提高查询性能
    logger.info("检查并创建索引以提高查询性能")
    try:
        # 为订单表的created_at字段添加索引，优化按时间查询和删除操作
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
        
        # 为订单表的status字段添加索引，优化按状态查询操作
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        
        # 为用户ID添加索引，优化按用户查询订单操作
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
        
        logger.info("数据库索引创建或更新完成")
    except Exception as e:
        logger.error(f"创建索引时出错: {str(e)}", exc_info=True)
    
    conn.close()

# 数据库执行函数
def execute_query(query, params=(), fetch=False, return_cursor=False):
    """执行数据库查询并返回结果"""
    logger.debug(f"执行查询: {query[:50]}... 参数: {params}")
    return execute_postgres_query(query, params, fetch, return_cursor)



def execute_postgres_query(query, params=(), fetch=False, return_cursor=False):
    """执行PostgreSQL查询并返回结果"""
    url = urlparse(DATABASE_URL)
    dbname = url.path[1:]
    user = url.username
    password = url.password
    host = url.hostname
    port = url.port
    
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port
    )
    cursor = conn.cursor()
    
    # PostgreSQL使用%s作为参数占位符，而不是SQLite的?
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

# ===== 密码加密 =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# 获取未通知订单
def get_unnotified_orders():
    """获取未通知的订单"""
    orders = execute_query("""
        SELECT id, account, password, package, created_at, web_user_id, remark 
        FROM orders 
        WHERE notified = 0 AND status = ?
    """, (STATUS['SUBMITTED'],), fetch=True)
    
    # 记录获取到的未通知订单
    if orders:
        logger.info(f"获取到 {len(orders)} 个未通知订单")
    
    return orders

# 获取订单详情
def get_order_details(oid):
    return execute_query("SELECT id, account, password, package, status, remark FROM orders WHERE id = ?", (oid,), fetch=True)

# ===== 卖家管理 =====
def get_all_sellers():
    """获取所有卖家列表"""
    try:
        return execute_query("""
            SELECT telegram_id, username, first_name, nickname, is_active, 
                   added_at, added_by, 
                   COALESCE(is_admin, FALSE) as is_admin,
                   COALESCE(distribution_level, 1) as distribution_level,
                   COALESCE(max_concurrent_orders, 5) as max_concurrent_orders,
                   COALESCE(participate_in_distribution, TRUE) as participate_in_distribution
            FROM sellers
            ORDER BY added_at DESC
        """, fetch=True)
    except Exception as e:
        logger.error(f"获取卖家列表失败: {str(e)}", exc_info=True)
        return []

def get_active_seller_ids():
    """获取所有活跃的卖家ID"""
    sellers = execute_query("SELECT telegram_id FROM sellers WHERE is_active = TRUE", fetch=True)
    
    return [seller[0] for seller in sellers] if sellers else []

def get_seller_info(telegram_id):
    """
    获取指定卖家的信息
    
    参数:
    - telegram_id: 卖家的Telegram ID
    
    返回:
    - 包含卖家信息的字典，如果卖家不存在则返回None
    """
    try:
        result = execute_query("""
            SELECT telegram_id, nickname, username, first_name, is_active
            FROM sellers
            WHERE telegram_id = %s
        """, (telegram_id,), fetch=True)
        
        if not result:
            logger.warning(f"卖家 {telegram_id} 不存在")
            return None
            
        seller = result[0]
        telegram_id, nickname, username, first_name, is_active = seller
        
        # 如果没有设置昵称，则使用first_name或username作为默认昵称
        display_name = nickname or first_name or f"Seller {telegram_id}"
        
        return {
            "telegram_id": telegram_id,
            "nickname": nickname,
            "username": username,
            "first_name": first_name, 
            "display_name": display_name,
            "is_active": bool(is_active)
        }
    except Exception as e:
        logger.error(f"获取卖家 {telegram_id} 信息失败: {str(e)}", exc_info=True)
        return None

def get_active_sellers():
    """获取所有活跃的卖家的ID和昵称"""
    sellers = execute_query("""
            SELECT telegram_id, nickname, username, first_name, 
                   last_active_at
            FROM sellers 
            WHERE is_active = TRUE
        """, fetch=True)
    
    result = []
    for seller in sellers:
        telegram_id, nickname, username, first_name, last_active_at = seller
        # 如果没有设置昵称，则使用first_name或username作为默认昵称
        display_name = nickname or first_name or f"卖家 {telegram_id}"
        result.append({
            "id": telegram_id,
            "name": display_name,
            "last_active_at": last_active_at or ""
        })
    return result

def add_seller(telegram_id, username, first_name, nickname, added_by):
    """添加新卖家"""
    timestamp = get_china_time()
    execute_query(
        "INSERT INTO sellers (telegram_id, username, first_name, nickname, added_at, added_by) VALUES (%s, %s, %s, %s, %s, %s)",
        (telegram_id, username, first_name, nickname, timestamp, added_by)
    )

def toggle_seller_status(telegram_id):
    """切换卖家活跃状态"""
    execute_query("UPDATE sellers SET is_active = NOT is_active WHERE telegram_id = %s", (telegram_id,))

def remove_seller(telegram_id):
    """移除卖家"""
    return execute_query("DELETE FROM sellers WHERE telegram_id=%s", (telegram_id,))

def toggle_seller_admin(telegram_id):
    """切换卖家的管理员状态"""
    try:
        # 先获取当前状态
        current = execute_query(
            "SELECT COALESCE(is_admin, FALSE) FROM sellers WHERE telegram_id = %s", 
            (telegram_id,), 
            fetch=True
        )
            
        if not current:
            return False
            
        new_status = not bool(current[0][0])
        
        execute_query(
            "UPDATE sellers SET is_admin = %s WHERE telegram_id = %s",
            (new_status, telegram_id)
        )
        return True
    except Exception as e:
        logger.error(f"切换卖家管理员状态失败: {e}")
        return False

def is_admin_seller(telegram_id):
    """检查卖家是否是管理员"""
    result = execute_query(
        "SELECT COALESCE(is_admin, FALSE) FROM sellers WHERE telegram_id = %s AND is_active = TRUE",
        (telegram_id,),
        fetch=True
    )
    return bool(result and result[0][0])


def update_seller_nickname(telegram_id, nickname):
    """更新卖家昵称"""
    execute_query(
        "UPDATE sellers SET nickname = %s WHERE telegram_id = %s",
        (nickname, telegram_id)
    )
    logger.info(f"已更新卖家 {telegram_id} 的昵称为 {nickname}")

def update_seller_last_active(telegram_id):
    """更新卖家最后活跃时间"""
    timestamp = get_china_time()
    execute_query(
        "UPDATE sellers SET last_active_at = %s WHERE telegram_id = %s",
        (timestamp, telegram_id)
    )

def update_seller_info(telegram_id, username=None, first_name=None):
    """更新卖家的Telegram信息（用户名和昵称）"""
    try:
        fields_to_update = []
        params = []
        
        # 根据数据库类型选择占位符
        placeholder = "%s"
        
        if username is not None:
            fields_to_update.append(f"username = {placeholder}")
            params.append(username)
            
        if first_name is not None:
            fields_to_update.append(f"first_name = {placeholder}")
            params.append(first_name)
            
        if not fields_to_update:
            return  # 没有需要更新的字段
            
        # 添加telegram_id到参数末尾
        params.append(telegram_id)
        
        # 构建SQL语句
        sql = f"UPDATE sellers SET {', '.join(fields_to_update)} WHERE telegram_id = {placeholder}"
        
        execute_query(sql, params)
        logger.info(f"已更新卖家 {telegram_id} 的信息: username={username}, first_name={first_name}")
    except Exception as e:
        logger.error(f"更新卖家 {telegram_id} 信息失败: {str(e)}", exc_info=True)

def get_today_valid_orders_count(user_id=None):
    """获取今日有效订单数
    
    有效订单数计算规则：
    - 充值成功的订单 (status = 'completed')
    - + 充值失败但已确认收到的订单 (status = 'failed' AND confirm_status = 'confirmed')  
    - + 已接单且买家已确认收到的订单 (status = 'accepted' AND confirm_status = 'confirmed')
    - - 充值成功但被标记长时间未收到的订单 (status = 'completed' AND confirm_status = 'not_received')
    
    Args:
        user_id: 如果指定，只计算该用户的订单；否则计算所有订单
    """
    from datetime import datetime
    import pytz
    
    today = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d")
    logger.info(f"查询今日({today})有效订单...")
    
    try:
        # 根据数据库类型构建查询
        base_query = """
            SELECT COUNT(*) FROM orders 
            WHERE (
                -- 充值成功且非长时间未收到
                (status = 'completed' AND (confirm_status IS NULL OR confirm_status != 'not_received'))
                OR
                -- 充值失败但已确认收到
                (status = 'failed' AND confirm_status = 'confirmed')
                OR
                -- 已接单且买家已确认收到
                (status = 'accepted' AND confirm_status = 'confirmed')
            )
            AND to_char(created_at::timestamp, 'YYYY-MM-DD') = %s
        """
        if user_id:
            query = base_query + " AND user_id = %s"
            params = (today, user_id)
        else:
            query = base_query
            params = (today,)
        
        result = execute_query(query, params, fetch=True)
        return result[0][0] if result else 0
    except Exception as e:
        logger.error(f"获取今日有效订单数失败: {str(e)}", exc_info=True)
        return 0

def get_today_valid_orders_count_by_tg_logic():
    """获取今日有效订单数 - 完全复制TG端管理员统计逻辑
    
    统计所有卖家的今日有效订单数总和，使用和TG端/stats命令完全相同的逻辑
    """
    from datetime import datetime
    import pytz
    
    today = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d")
    logger.info(f"使用TG端逻辑查询今日({today})有效订单...")
    
    try:
        # 获取所有卖家
        sellers = get_all_sellers()
        if not sellers:
            logger.info("没有找到任何卖家")
            return 0
        
        total_orders = 0
        
        for seller in sellers:
            telegram_id = seller[0]
            
            # 获取该卖家今日有效订单数 - 完全复制TG端的查询逻辑
            seller_orders_result = execute_query("""
                SELECT COUNT(*) FROM orders 
                WHERE accepted_by = %s
                AND (
                    -- 充值成功且非长时间未收到
                    (status = 'completed' AND (confirm_status IS NULL OR confirm_status != 'not_received'))
                    OR
                    -- 充值失败但已确认收到
                    (status = 'failed' AND confirm_status = 'confirmed')
                    OR
                    -- 已接单且买家已确认收到
                    (status = 'accepted' AND confirm_status = 'confirmed')
                )
                AND to_char(created_at::timestamp, 'YYYY-MM-DD') = %s
            """, (str(telegram_id), today), fetch=True)
            
            valid_orders = seller_orders_result[0][0] if seller_orders_result else 0
            total_orders += valid_orders
            
            if valid_orders > 0:
                logger.info(f"卖家 {telegram_id} 今日有效订单数: {valid_orders}")
        
        logger.info(f"使用TG端逻辑，今日有效订单总数: {total_orders}")
        return total_orders
    except Exception as e:
        logger.error(f"使用TG端逻辑获取今日有效订单数失败: {str(e)}", exc_info=True)
        return 0

def get_all_today_confirmed_count():
    """获取所有用户今天已确认的订单总数"""
    from datetime import datetime
    import pytz
    
    today = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d")
    logger.info(f"查询今日({today})充值成功订单...")
    
    try:
        # 首先，查询所有状态为completed的订单，不考虑日期
        all_completed_query = "SELECT id, status, updated_at FROM orders WHERE status = 'completed'"
        all_completed = execute_query(all_completed_query, (), fetch=True)
        logger.info(f"所有充值成功订单数: {len(all_completed) if all_completed else 0}")
        if all_completed:
            for order in all_completed:
                logger.info(f"订单ID: {order[0]}, 状态: {order[1]}, 更新时间: {order[2]}")
        
        # 根据数据库类型选择不同查询语句
        methods = [
            {
                "name": "to_char方法",
                "query": """
                    SELECT COUNT(*) FROM orders 
                    WHERE status = 'completed' 
                    AND to_char(updated_at::timestamp, 'YYYY-MM-DD') = %s
                """,
                "params": (today,)
            },
            {
                "name": "substring方法",
                "query": """
                    SELECT COUNT(*) FROM orders 
                    WHERE status = 'completed' 
                    AND substring(updated_at, 1, 10) = %s
                """,
                "params": (today,)
            },
            {
                "name": "LIKE方法",
                "query": """
                    SELECT COUNT(*) FROM orders 
                    WHERE status = 'completed' 
                    AND updated_at LIKE %s
                """,
                "params": (f"{today}%",)
            }
        ]
        
        # 尝试所有方法
        for method in methods:
            try:
                result = execute_query(method["query"], method["params"], fetch=True)
                count = result[0][0] if result and result[0] else 0
                logger.info(f"使用{method['name']}查询结果: {count}")
                
                # 如果找到了结果，就返回
                if count > 0:
                    logger.info(f"今日全站充值成功订单数: {count}, 查询方法: {method['name']}")
                    return count
            except Exception as e:
                logger.error(f"使用{method['name']}查询失败: {str(e)}")
        
        # 如果所有方法都没有找到结果，返回0
        logger.warning("所有查询方法都返回0，可能是日期格式问题")
        return 0
    except Exception as e:
        logger.error(f"获取全站今日确认订单数失败: {str(e)}", exc_info=True)
        return 0

def get_seller_today_confirmed_orders_by_user(telegram_id):
    """获取卖家今天已确认的订单数，并按用户分组"""
    from datetime import datetime
    import pytz
    today = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d")
    
    try:
        results = execute_query(
            """
            SELECT web_user_id, COUNT(*) 
            FROM orders 
            WHERE accepted_by = %s 
            AND status = 'completed' 
            AND to_char(updated_at::timestamp, 'YYYY-MM-DD') = %s
            GROUP BY web_user_id
            """,
            (str(telegram_id), today),
            fetch=True
        )
        
        logger.info(f"卖家 {telegram_id} 今日充值成功订单数: {len(results) if results else 0}")
        return results if results else []
    except Exception as e:
        logger.error(f"获取卖家 {telegram_id} 今日确认订单数失败: {str(e)}", exc_info=True)
        # 返回空列表而不是抛出异常，避免影响stats功能
        return []

def get_seller_pending_orders(telegram_id):
    """获取卖家当前未完成的订单数（已接单但未确认）"""
    result = execute_query(
        """
        SELECT COUNT(*) FROM orders 
        WHERE accepted_by = %s 
        AND status != '已取消' 
        AND (buyer_confirmed IS NULL OR buyer_confirmed = FALSE)
        """,
        (telegram_id,),
        fetch=True
    )
    
    if result and len(result) > 0:
        return result[0][0]
    return 0

def check_seller_completed_orders(telegram_id):
    """检查卖家完成的订单数量"""
    orders = get_seller_completed_orders(telegram_id)
    return len(orders) if orders else 0

def get_seller_current_orders_count(telegram_id):
    """
    获取卖家最近1小时内未完成的订单数量
    
    参数:
    - telegram_id: 卖家的Telegram ID
    
    返回:
    - 最近1小时内未完成订单数量
    """
    try:
        # 获取1小时前的时间戳
        one_hour_ago = datetime.now() - timedelta(hours=1)
        one_hour_ago_str = one_hour_ago.strftime("%Y-%m-%d %H:%M:%S")
        
        # 查询最近1小时内非完成/失败/取消的订单
        result = execute_query("""
            SELECT COUNT(*) FROM orders 
            WHERE accepted_by = %s 
            AND status NOT IN (%s, %s, %s)
            AND accepted_at >= %s
        """, (str(telegram_id), STATUS['COMPLETED'], STATUS['FAILED'], STATUS['CANCELLED'], one_hour_ago_str), fetch=True)
            
        count = result[0][0] if result else 0
        logger.info(f"卖家 {telegram_id} 最近1小时内有效订单数: {count}")
        return count
    except Exception as e:
        logger.error(f"获取卖家当前订单数量失败: {e}", exc_info=True)
        return 0

def check_all_sellers_full():
    """
    检查是否所有活跃且参与分流的卖家都已达到最大接单量
    
    返回:
    - True: 所有卖家都已满
    - False: 至少有一个卖家未满
    """
    try:
        # 获取所有活跃且参与分流的卖家
        active_sellers = get_participating_sellers()
        
        if not active_sellers:
            logger.warning("没有活跃且参与分流的卖家，订单提交受限")
            return True  # 没有活跃且参与分流的卖家时返回True（不允许接单）
        
        for seller in active_sellers:
            seller_id = seller["id"]
            
            # 获取卖家最大接单量
            max_orders_result = execute_query("""
                SELECT max_concurrent_orders FROM sellers 
                WHERE telegram_id = %s
            """, (seller_id,), fetch=True)
                
            max_orders = max_orders_result[0][0] if max_orders_result else 5  # 默认值为5
            
            # 获取当前接单量
            current_orders = get_seller_current_orders_count(seller_id)
            
            logger.info(f"卖家 {seller_id} 当前订单: {current_orders}, 最大接单: {max_orders}")
            
            # 如果有卖家未达到最大接单量，返回False
            if current_orders < max_orders:
                return False
        
        # 所有卖家都已达到最大接单量
        logger.warning("所有卖家都已达到最大接单量，订单提交受限")
        return True
    except Exception as e:
        logger.error(f"检查卖家接单状态时出错: {e}", exc_info=True)
        return False  # 发生错误时默认允许提交订单

def select_active_seller():
    """
    从所有活跃且参与分流的卖家中选择一个卖家接单
    
    选择逻辑：
    1. 获取所有活跃且参与分流的卖家
    2. 筛选出当前接单数小于最大接单量的卖家
    3. 基于分流等级进行加权随机选择，等级越高被选中的概率越大
    
    返回:
    - 卖家ID，如果没有可用卖家则返回None
    """
    try:
        active_sellers = get_participating_sellers()
        
        if not active_sellers:
            logger.warning("没有活跃且参与分流的卖家可用于选择")
            return None
            
        available_sellers = []
        total_weight = 0
        
        # 检查每个活跃卖家的当前接单数
        for seller in active_sellers:
            seller_id = seller["id"]
            
            # 获取卖家最大接单量和分流等级
            seller_info = execute_query("""
                SELECT max_concurrent_orders, distribution_level FROM sellers 
                WHERE telegram_id = %s
            """, (seller_id,), fetch=True)
                
            max_orders = seller_info[0][0] if seller_info else 5
            distribution_level = seller_info[0][1] if seller_info and len(seller_info[0]) > 1 else 1
            
            # 获取当前接单量
            current_orders = get_seller_current_orders_count(seller_id)
            
            # 如果卖家当前接单数小于最大接单量，则添加到可用卖家列表
            if current_orders < max_orders:
                # 权重就是分流等级，确保分流等级至少为1
                weight = max(1, distribution_level)
                total_weight += weight
                
                available_sellers.append({
                    "id": seller_id,
                    "current_orders": current_orders,
                    "max_orders": max_orders,
                    "distribution_level": distribution_level,
                    "weight": weight
                })
        
        if not available_sellers:
            logger.warning("没有可用的卖家（所有卖家都已达到最大接单量）")
            return None
        
        # 如果只有一个可用卖家，直接返回
        if len(available_sellers) == 1:
            selected_seller = available_sellers[0]
            logger.info(f"只有一个可用卖家: {selected_seller['id']}, 当前接单: {selected_seller['current_orders']}/{selected_seller['max_orders']}, 分流等级: {selected_seller['distribution_level']}")
            return selected_seller["id"]
        
        # 使用加权随机选择，等级越高被选中的概率越大
        # 计算每个卖家的选择概率范围
        cumulative_weight = 0
        for seller in available_sellers:
            seller["cumulative_weight_start"] = cumulative_weight
            cumulative_weight += seller["weight"]
            seller["cumulative_weight_end"] = cumulative_weight
        
        # 随机选择一个值
        random_value = random.uniform(0, total_weight)
        
        # 找到对应的卖家
        selected_seller = None
        for seller in available_sellers:
            if seller["cumulative_weight_start"] <= random_value < seller["cumulative_weight_end"]:
                selected_seller = seller
                break
        
        # 如果没有选中（理论上不应该发生），选择第一个可用卖家
        if not selected_seller:
            selected_seller = available_sellers[0]
        
        logger.info(f"选择卖家: {selected_seller['id']}, 当前接单: {selected_seller['current_orders']}/{selected_seller['max_orders']}, 分流等级: {selected_seller['distribution_level']}")
        return selected_seller["id"]
    
    except Exception as e:
        logger.error(f"选择活跃卖家失败: {str(e)}", exc_info=True)
        return None

def check_seller_activity(telegram_id):
    """向卖家发送活跃度检查请求"""
    # 记录检查请求时间
    timestamp = get_china_time()
    execute_query(
        "UPDATE sellers SET activity_check_at = %s WHERE telegram_id = %s",
        (timestamp, telegram_id)
    )
    return True



def create_order_with_deduction_atomic(account, password, package, remark, username, user_id):
    """创建订单（已移除余额扣除功能）"""
    try:
        # 创建订单记录
        now = get_china_time()
        
        # 根据数据库类型选择不同的SQL
        execute_query(
            """
            INSERT INTO orders (account, password, package, status, created_at, remark, user_id, web_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (account, password, package, 'submitted', now, remark, user_id, username)
        )
            
        return True, "订单创建成功", 0, 0
    except Exception as e:
        logger.error(f"创建订单失败: {str(e)}", exc_info=True)
        return False, f"创建订单失败: {str(e)}", None, None

def check_duplicate_remark(user_id, remark):
    """
    检查当前用户今日订单中是否存在重复的备注
    
    参数:
    - user_id: 用户ID
    - remark: 要检查的备注
    
    返回:
    - 如果存在重复，返回True，否则返回False
    """
    if not remark or remark.strip() == '':
        # 空备注不检查重复
        return False
        
    try:
        # 获取今天的日期，格式为YYYY-MM-DD
        today = datetime.now(CN_TIMEZONE).strftime("%Y-%m-%d")
        
        # 根据数据库类型选择不同查询语句
        query = """
            SELECT COUNT(*) FROM orders 
            WHERE user_id = %s 
            AND remark = %s 
            AND created_at LIKE %s
        """
        params = (user_id, remark, f"{today}%")
        
        result = execute_query(query, params, fetch=True)
        count = result[0][0] if result and result[0] else 0
        
        return count > 0
    except Exception as e:
        logger.error(f"检查备注重复失败: {str(e)}", exc_info=True)
        return False

def delete_old_orders(days=3):
    """
    删除指定天数前的订单数据
    
    参数:
    - days: 天数，默认为3天
    
    返回:
    - 已删除的订单数量
    """
    try:
        # 计算截止日期（当前时间减去指定天数）
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_date_str = cutoff_date.strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"开始删除 {days} 天前的订单数据（截止日期：{cutoff_date_str}）")
        
        # 执行删除操作
        result = execute_query(
            "DELETE FROM orders WHERE created_at < %s RETURNING id",
            (cutoff_date_str,),
            fetch=True
        )
        deleted_count = len(result) if result else 0
        
        logger.info(f"已删除 {deleted_count} 条过期订单数据")
        return deleted_count
    except Exception as e:
        logger.error(f"删除旧订单数据失败: {str(e)}", exc_info=True)
        return 0

def toggle_seller_distribution_participation(telegram_id):
    """切换卖家参与分流状态"""
    try:
        execute_query("UPDATE sellers SET participate_in_distribution = NOT participate_in_distribution WHERE telegram_id = %s", (telegram_id,))
        return True
    except Exception as e:
        logger.error(f"切换卖家参与分流状态失败: {e}")
        return False

def set_seller_distribution_participation(telegram_id, participate):
    """设置卖家参与分流状态"""
    try:
        execute_query("UPDATE sellers SET participate_in_distribution = %s WHERE telegram_id = %s", (participate, telegram_id))
        return True
    except Exception as e:
        logger.error(f"设置卖家参与分流状态失败: {e}")
        return False

def get_participating_sellers():
    """获取所有活跃且参与分流的卖家的ID和昵称"""
    sellers = execute_query("""
            SELECT telegram_id, nickname, username, first_name, 
                   last_active_at
            FROM sellers 
            WHERE is_active = TRUE AND participate_in_distribution = TRUE
        """, fetch=True)
    
    result = []
    for seller in sellers:
        telegram_id, nickname, username, first_name, last_active_at = seller
        # 如果没有设置昵称，则使用first_name或username作为默认昵称
        display_name = nickname or first_name or f"卖家 {telegram_id}"
        result.append({
            "id": telegram_id,
            "name": display_name,
            "last_active_at": last_active_at or ""
        })
    return result

def get_seller_participation_status(telegram_id):
    """获取卖家的参与分流状态"""
    try:
        result = execute_query(
            "SELECT participate_in_distribution, is_active FROM sellers WHERE telegram_id = %s", 
            (str(telegram_id),), 
            fetch=True
        )
        if result:
            participate, active = result[0]
            return {
                "participate_in_distribution": bool(participate),
                "is_active": bool(active)
            }
        return None
    except Exception as e:
        logger.error(f"获取卖家参与状态失败: {e}")
        return None

def get_user_last_remark(user_id):
    """
    获取用户今日的上一条订单备注
    
    参数:
    - user_id: 用户ID
    
    返回:
    - 用户今日上一条订单的备注内容，如果没有订单则返回None
    """
    try:
        # 获取今天的日期，格式为YYYY-MM-DD
        today = datetime.now(CN_TIMEZONE).strftime("%Y-%m-%d")
        
        
        query = """
            SELECT remark FROM orders 
            WHERE user_id = %s 
            AND created_at LIKE %s
            ORDER BY created_at DESC 
            LIMIT 1
        """
        params = (user_id, f"{today}%")
        
        result = execute_query(query, params, fetch=True)
        
        if result and result[0] and result[0][0]:
            return result[0][0]
        return None
    except Exception as e:
        logger.error(f"获取用户今日上一条备注失败: {str(e)}", exc_info=True)
        return None

def is_pure_number(text):
    """
    检查文本是否为纯数字
    
    参数:
    - text: 要检查的文本
    
    返回:
    - 如果是纯数字返回True，否则返回False
    """
    if not text:
        return False
    
    # 去除首尾空格
    text = text.strip()
    
    # 检查是否为空
    if not text:
        return False
    
    # 检查是否为纯数字
    return text.isdigit()

def check_db_connection():
    """检查PostgreSQL数据库连接是否正常"""
    try:
        url = urlparse(DATABASE_URL)
        dbname = url.path[1:]
        user = url.username
        password = url.password
        host = url.hostname
        port = url.port
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port
        )
        conn.close()
        logger.info("数据库连接正常")
        return True
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}", exc_info=True)
        return False