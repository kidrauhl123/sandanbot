from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
import logging
from modules.database import execute_query, get_all_sellers
from modules.constants import STATUS_TEXT_ZH
from modules.auth import login_required, admin_required, authenticate_user, create_user, get_user_by_id, get_all_users, update_user_role, delete_user

logger = logging.getLogger(__name__)

def register_routes(app: Flask):
    """注册所有Web路由"""
    
    @app.route('/')
    def index():
        """主页"""
        user = None
        if 'user_id' in session:
            user = get_user_by_id(session['user_id'])
        return render_template('index.html', user=user)
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """用户登录"""
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            if not username or not password:
                flash('请输入用户名和密码', 'error')
                return render_template('login.html')
            
            success, message, user_data = authenticate_user(username, password)
            
            if success:
                session['user_id'] = user_data['id']
                session['username'] = user_data['username']
                session['role'] = user_data['role']
                flash('登录成功！', 'success')
                return redirect(url_for('index'))
            else:
                flash(message, 'error')
        
        return render_template('login.html')
    
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        """用户注册"""
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            email = request.form.get('email')
            
            if not username or not password or not email:
                flash('请填写所有必填字段', 'error')
                return render_template('register.html')
            
            success, message = create_user(username, password, email)
            
            if success:
                flash('注册成功！请登录', 'success')
                return redirect(url_for('login'))
            else:
                flash(message, 'error')
        
        return render_template('register.html')
    
    @app.route('/logout')
    def logout():
        """用户登出"""
        session.clear()
        flash('已成功登出', 'success')
        return redirect(url_for('index'))
    
    @app.route('/orders')
    @login_required
    def orders():
        """订单管理页面 - 需要登录"""
        user = get_user_by_id(session['user_id'])
        orders = execute_query(
            "SELECT id, account, package, status, created_at, remark, user_id FROM orders ORDER BY id DESC LIMIT 50",
            fetch=True
        )
        return render_template('orders.html', orders=orders, status_text=STATUS_TEXT_ZH, user=user)
    
    @app.route('/sellers')
    @admin_required
    def sellers():
        """卖家管理页面 - 需要管理员权限"""
        user = get_user_by_id(session['user_id'])
        sellers = get_all_sellers()
        return render_template('sellers.html', sellers=sellers, user=user)
    
    @app.route('/admin')
    @admin_required
    def admin():
        """管理员面板 - 需要管理员权限"""
        user = get_user_by_id(session['user_id'])
        users = get_all_users()
        return render_template('admin.html', users=users, user=user)
    
    @app.route('/profile')
    @login_required
    def profile():
        """用户个人资料页面"""
        user = get_user_by_id(session['user_id'])
        return render_template('profile.html', user=user)
    
    # API路由
    @app.route('/api/users', methods=['GET'])
    @admin_required
    def get_users_api():
        """获取用户列表API - 仅管理员"""
        users = get_all_users()
        return jsonify({'success': True, 'users': users})
    
    @app.route('/api/users/<int:user_id>/role', methods=['PUT'])
    @admin_required
    def update_user_role_api(user_id):
        """更新用户角色API - 仅管理员"""
        data = request.get_json()
        new_role = data.get('role')
        
        if new_role not in ['user', 'admin']:
            return jsonify({'success': False, 'message': '无效的角色'}), 400
        
        success, message = update_user_role(user_id, new_role)
        return jsonify({'success': success, 'message': message})
    
    @app.route('/api/users/<int:user_id>', methods=['DELETE'])
    @admin_required
    def delete_user_api(user_id):
        """删除用户API - 仅管理员"""
        if user_id == session['user_id']:
            return jsonify({'success': False, 'message': '不能删除自己的账户'}), 400
        
        success, message = delete_user(user_id)
        return jsonify({'success': success, 'message': message}) 