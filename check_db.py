import sqlite3
import os

def check_and_fix_database():
    """检查并修复数据库表结构"""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("检查数据库表结构...")
        
        # 检查users表结构
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        print(f"users表的列: {columns}")
        
        # 检查是否缺少last_login字段
        if 'last_login' not in columns:
            print("添加缺失的last_login字段...")
            cursor.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
            conn.commit()
            print("last_login字段添加成功")
        
        # 检查是否缺少balance字段
        if 'balance' not in columns:
            print("添加缺失的balance字段...")
            cursor.execute("ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0")
            conn.commit()
            print("balance字段添加成功")
        
        # 检查是否缺少credit_limit字段
        if 'credit_limit' not in columns:
            print("添加缺失的credit_limit字段...")
            cursor.execute("ALTER TABLE users ADD COLUMN credit_limit REAL DEFAULT 0")
            conn.commit()
            print("credit_limit字段添加成功")
        
        # 重新检查表结构
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        print(f"修复后users表的列: {columns}")
        
        # 检查用户数据
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        print(f"用户总数: {user_count}")
        
        if user_count > 0:
            cursor.execute("SELECT id, username, is_admin, created_at, last_login, balance, credit_limit FROM users LIMIT 5")
            users = cursor.fetchall()
            print("前5个用户:")
            for user in users:
                print(f"  用户: {user}")
        
        conn.close()
        print("数据库检查完成")
        
    except Exception as e:
        print(f"数据库检查失败: {e}")

if __name__ == "__main__":
    check_and_fix_database() 