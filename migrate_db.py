#!/usr/bin/env python3
"""
数据库迁移脚本
用于处理现有数据库结构的升级
"""

import logging
from modules.database import execute_query
from modules.constants import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """执行数据库迁移"""
    try:
        logger.info("开始数据库迁移...")
        
        # 检查users表是否存在
        result = execute_query("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'users'
            )
        """, fetch=True)
        
        if result and result[0][0]:
            logger.info("users表已存在，检查表结构...")
            
            # 检查是否有password_hash列
            result = execute_query("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'password_hash'
            """, fetch=True)
            
            if result:
                logger.info("检测到旧版本users表，开始迁移...")
                
                # 备份现有数据
                execute_query("""
                    CREATE TABLE users_backup AS 
                    SELECT * FROM users
                """)
                logger.info("已创建users表备份")
                
                # 删除旧表
                execute_query("DROP TABLE users CASCADE")
                logger.info("已删除旧users表")
                
                # 创建新表
                execute_query("""
                    CREATE TABLE users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password VARCHAR(255) NOT NULL,
                        email VARCHAR(100),
                        role VARCHAR(20) DEFAULT 'user',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP
                    )
                """)
                logger.info("已创建新users表")
                
                # 恢复数据（如果有的话）
                try:
                    execute_query("""
                        INSERT INTO users (username, password, email, role, created_at)
                        SELECT 
                            username, 
                            password_hash, 
                            NULL as email, 
                            CASE WHEN is_admin THEN 'admin' ELSE 'user' END as role,
                            created_at
                        FROM users_backup
                    """)
                    logger.info("已恢复用户数据")
                except Exception as e:
                    logger.warning(f"恢复用户数据时出错: {str(e)}")
                
                # 删除备份表
                execute_query("DROP TABLE users_backup")
                logger.info("已删除备份表")
            else:
                logger.info("users表结构已是最新版本")
        else:
            logger.info("users表不存在，创建新表...")
            execute_query("""
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    email VARCHAR(100),
                    role VARCHAR(20) DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
        
        # 确保sellers表存在
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
        
        # 检查orders表是否有package字段，如果有则删除
        result = execute_query("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'orders' AND column_name = 'package'
        """, fetch=True)
        
        if result:
            logger.info("检测到orders表有package字段，开始删除...")
            
            # 创建新的orders表（没有package字段）
            execute_query("""
                CREATE TABLE IF NOT EXISTS orders_new (
                    id SERIAL PRIMARY KEY,
                    account VARCHAR(255) NOT NULL,
                    password VARCHAR(255),
                    status VARCHAR(20) DEFAULT 'submitted',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    accepted_by VARCHAR(50),
                    remark TEXT,
                    user_id INTEGER REFERENCES users(id),
                    web_user_id VARCHAR(50),
                    qr_code_path VARCHAR(500)
                )
            """)
            
            # 复制数据（除了package字段）
            try:
                execute_query("""
                    INSERT INTO orders_new (id, account, password, status, created_at, accepted_at, completed_at, accepted_by, remark, user_id, web_user_id)
                    SELECT id, account, password, status, created_at, accepted_at, completed_at, accepted_by, remark, user_id, web_user_id
                    FROM orders
                """)
                logger.info("已复制orders数据")
                
                # 删除旧表并重命名新表
                execute_query("DROP TABLE orders CASCADE")
                execute_query("ALTER TABLE orders_new RENAME TO orders")
                logger.info("已删除package字段并更新orders表结构")
            except Exception as e:
                logger.warning(f"迁移orders表时出错: {str(e)}")
                # 如果出错，直接创建新表
                execute_query("DROP TABLE IF EXISTS orders_new")
                execute_query("""
                    CREATE TABLE orders (
                        id SERIAL PRIMARY KEY,
                        account VARCHAR(255) NOT NULL,
                        password VARCHAR(255),
                        status VARCHAR(20) DEFAULT 'submitted',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        accepted_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        accepted_by VARCHAR(50),
                        remark TEXT,
                        user_id INTEGER REFERENCES users(id),
                        web_user_id VARCHAR(50),
                        qr_code_path VARCHAR(500)
                    )
                """)
                logger.info("已创建新的orders表（无package字段）")
        else:
            # orders表不存在或没有package字段，直接创建正确的表结构
            execute_query("""
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    account VARCHAR(255) NOT NULL,
                    password VARCHAR(255),
                    status VARCHAR(20) DEFAULT 'submitted',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    accepted_by VARCHAR(50),
                    remark TEXT,
                    user_id INTEGER REFERENCES users(id),
                    web_user_id VARCHAR(50),
                    qr_code_path VARCHAR(500)
                )
            """)
            logger.info("已创建orders表（包含qr_code_path字段）")
        
        # 创建默认管理员用户
        from modules.database import hash_password
        admin_password = hash_password('z755439')
        
        # 检查管理员是否已存在
        result = execute_query("SELECT id FROM users WHERE username = 'admin'", fetch=True)
        if not result:
            execute_query("""
                INSERT INTO users (username, password, email, role) 
                VALUES ('admin', %s, 'admin@example.com', 'admin')
            """, (admin_password,))
            logger.info("已创建默认管理员账户: admin / z755439")
        else:
            # 更新管理员密码
            execute_query("""
                UPDATE users SET password = %s WHERE username = 'admin'
            """, (admin_password,))
            logger.info("已更新管理员密码: admin / z755439")
        
        logger.info("数据库迁移完成！")
        return True
        
    except Exception as e:
        logger.error(f"数据库迁移失败: {str(e)}")
        return False

if __name__ == "__main__":
    migrate_database() 