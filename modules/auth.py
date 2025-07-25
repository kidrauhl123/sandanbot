import logging
from functools import wraps
from flask import session, redirect, url_for, flash, request
from modules.database import execute_query, hash_password

logger = logging.getLogger(__name__)

def login_required(f):
    """登录装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """管理员权限装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        
        user_id = session.get('user_id')
        if not user_id or not is_admin(user_id):
            flash('需要管理员权限', 'error')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

def create_user(username, password, email, role='user'):
    """创建新用户"""
    try:
        hashed_password = hash_password(password)
        execute_query(
            "INSERT INTO users (username, password, email, role) VALUES (%s, %s, %s, %s)",
            (username, hashed_password, email, role)
        )
        return True, "用户创建成功"
    except Exception as e:
        logger.error(f"创建用户失败: {str(e)}")
        return False, f"创建用户失败: {str(e)}"

def authenticate_user(username, password):
    """验证用户登录"""
    try:
        result = execute_query(
            "SELECT id, username, password, role, email FROM users WHERE username = %s",
            (username,), fetch=True
        )
        
        if not result:
            return False, "用户名或密码错误", None
        
        user = result[0]
        user_id, db_username, db_password, role, email = user
        
        if hash_password(password) == db_password:
            return True, "登录成功", {
                'id': user_id,
                'username': db_username,
                'role': role,
                'email': email
            }
        else:
            return False, "用户名或密码错误", None
            
    except Exception as e:
        logger.error(f"用户认证失败: {str(e)}")
        return False, f"认证失败: {str(e)}", None

def get_user_by_id(user_id):
    """根据用户ID获取用户信息"""
    try:
        result = execute_query(
            "SELECT id, username, role, email, created_at FROM users WHERE id = %s",
            (user_id,), fetch=True
        )
        
        if not result:
            return None
        
        user = result[0]
        return {
            'id': user[0],
            'username': user[1],
            'role': user[2],
            'email': user[3],
            'created_at': user[4]
        }
    except Exception as e:
        logger.error(f"获取用户信息失败: {str(e)}")
        return None

def is_admin(user_id):
    """检查用户是否为管理员"""
    try:
        result = execute_query(
            "SELECT role FROM users WHERE id = %s",
            (user_id,), fetch=True
        )
        
        if not result:
            return False
        
        return result[0][0] == 'admin'
    except Exception as e:
        logger.error(f"检查管理员权限失败: {str(e)}")
        return False

def get_all_users():
    """获取所有用户列表（仅管理员可用）"""
    try:
        result = execute_query(
            "SELECT id, username, email, role, created_at FROM users ORDER BY created_at DESC",
            fetch=True
        )
        
        users = []
        for row in result:
            users.append({
                'id': row[0],
                'username': row[1],
                'email': row[2],
                'role': row[3],
                'created_at': row[4]
            })
        
        return users
    except Exception as e:
        logger.error(f"获取用户列表失败: {str(e)}")
        return []

def update_user_role(user_id, new_role):
    """更新用户角色（仅管理员可用）"""
    try:
        execute_query(
            "UPDATE users SET role = %s WHERE id = %s",
            (new_role, user_id)
        )
        return True, "用户角色更新成功"
    except Exception as e:
        logger.error(f"更新用户角色失败: {str(e)}")
        return False, f"更新失败: {str(e)}"

def delete_user(user_id):
    """删除用户（仅管理员可用）"""
    try:
        execute_query("DELETE FROM users WHERE id = %s", (user_id,))
        return True, "用户删除成功"
    except Exception as e:
        logger.error(f"删除用户失败: {str(e)}")
        return False, f"删除失败: {str(e)}" 