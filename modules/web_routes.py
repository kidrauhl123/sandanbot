from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
import logging
import os
import uuid
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from modules.database import execute_query, get_all_sellers, create_order_with_deduction_atomic
from modules.constants import STATUS_TEXT_ZH
from modules.auth import login_required, admin_required, authenticate_user, create_user, get_user_by_id, get_all_users, update_user_role, delete_user

logger = logging.getLogger(__name__)

# 文件上传配置
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def register_routes(app: Flask):
    """注册所有Web路由"""
    
    @app.route('/', methods=['GET', 'POST'])
    def index():
        """主页"""
        if request.method == 'POST':
            # 处理订单创建
            if 'user_id' not in session:
                return jsonify({'success': False, 'message': '请先登录'}), 401
            
            try:
                # 获取表单数据 - 支持文件上传
                qr_code_file = request.files.get('qr_code')
                package = request.form.get('package', '12')  # 默认套餐
                preferred_seller = request.form.get('preferred_seller')
                remark = request.form.get('remark', '')
                
                # 获取账号信息 - 从二维码或其他方式获取
                account = 'AUTO_GENERATED'  # 这里可以添加二维码解析逻辑
                
                # 处理文件上传
                if qr_code_file and allowed_file(qr_code_file.filename):
                    # 生成唯一文件名
                    filename = secure_filename(qr_code_file.filename)
                    name, ext = os.path.splitext(filename)
                    unique_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
                    
                    # 确保上传目录存在
                    upload_path = os.path.join(app.root_path, UPLOAD_FOLDER)
                    os.makedirs(upload_path, exist_ok=True)
                    
                    # 保存文件
                    file_path = os.path.join(upload_path, unique_filename)
                    qr_code_file.save(file_path)
                    
                    # 可以在这里添加二维码解析逻辑来获取账号信息
                    account = f"QR_{unique_filename}"
                
                # 获取用户信息
                user_id = session.get('user_id')
                user = get_user_by_id(user_id)
                username = user['username'] if user else 'unknown'
                
                # 创建订单
                success, message, _, _ = create_order_with_deduction_atomic(
                    account, '', package, remark, username, user_id
                )
                
                if success:
                    return jsonify({'success': True, 'message': '订单创建成功'})
                else:
                    return jsonify({'success': False, 'message': message}), 400
                    
            except Exception as e:
                logger.error(f"创建订单失败: {str(e)}")
                return jsonify({'success': False, 'message': '创建订单失败'}), 500
        
        # GET请求 - 显示主页
        user = None
        user_id = session.get('user_id')
        if user_id:
            user = get_user_by_id(user_id)
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
                session['is_admin'] = user_data['role'] == 'admin'
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
        user = get_user_by_id(session.get('user_id'))
        orders = execute_query(
            "SELECT id, account, package, status, created_at, remark, user_id FROM orders ORDER BY id DESC LIMIT 50",
            fetch=True
        )
        return render_template('orders.html', orders=orders, status_text=STATUS_TEXT_ZH, user=user)
    
    @app.route('/sellers')
    @admin_required
    def sellers():
        """卖家管理页面 - 需要管理员权限"""
        user = get_user_by_id(session.get('user_id'))
        sellers = get_all_sellers()
        return render_template('sellers.html', sellers=sellers, user=user)
    
    @app.route('/admin')
    @admin_required
    def admin():
        """管理员面板 - 需要管理员权限"""
        user = get_user_by_id(session.get('user_id'))
        users = get_all_users()
        return render_template('admin.html', users=users, user=user)
    
    @app.route('/profile')
    @login_required
    def profile():
        """用户个人资料页面"""
        user = get_user_by_id(session.get('user_id'))
        return render_template('profile.html', user=user)
    
    @app.route('/dashboard')
    @login_required
    def dashboard():
        """用户仪表板页面"""
        user = get_user_by_id(session.get('user_id'))
        # 可以重定向到个人资料页面或者创建一个新的dashboard页面
        return redirect(url_for('profile'))
    
    # ==================== API路由 ====================
    
    @app.route('/api/orders', methods=['POST'])
    @login_required
    def create_order():
        """创建新订单"""
        try:
            account = request.form.get('account')
            password = request.form.get('password', '')
            package = request.form.get('package')
            remark = request.form.get('remark', '')
            preferred_seller = request.form.get('preferred_seller')
            
            if not account or not package:
                return jsonify({'success': False, 'message': '账号和套餐不能为空'}), 400
            
            # 获取用户信息
            user_id = session.get('user_id')
            user = get_user_by_id(user_id)
            username = user['username'] if user else 'unknown'
            
            # 创建订单
            success, message, _, _ = create_order_with_deduction_atomic(
                account, password, package, remark, username, user_id
            )
            
            if success:
                return jsonify({'success': True, 'message': '订单创建成功'})
            else:
                return jsonify({'success': False, 'message': message}), 400
                
        except Exception as e:
            logger.error(f"创建订单失败: {str(e)}")
            return jsonify({'success': False, 'message': '创建订单失败'}), 500
    
    @app.route('/api/quick-orders')
    def get_quick_orders():
        """获取订单列表"""
        try:
            limit = request.args.get('limit', 50, type=int)
            page = request.args.get('page', 1, type=int)
            offset = (page - 1) * limit
            
            # 检查用户是否登录
            user_id = session.get('user_id')
            
            if not user_id:
                # 未登录用户返回空列表，不报错
                return jsonify({
                    'success': True,
                    'orders': [],
                    'message': '请登录查看订单',
                    'timestamp': datetime.now().timestamp()
                })
            
            # 根据用户权限决定查询范围
            if session.get('role') == 'admin':
                # 管理员可以看到所有订单
                orders = execute_query("""
                    SELECT o.id, o.account, o.package, o.status, o.created_at, 
                           o.accepted_at, o.completed_at, o.remark, o.accepted_by,
                           o.web_user_id as username, s.nickname as accepted_by_nickname
                    FROM orders o 
                    LEFT JOIN sellers s ON o.accepted_by = s.telegram_id::text
                    ORDER BY o.id DESC LIMIT %s OFFSET %s
                """, (limit, offset), fetch=True)
            else:
                # 普通用户只能看到自己的订单
                orders = execute_query("""
                    SELECT o.id, o.account, o.package, o.status, o.created_at, 
                           o.accepted_at, o.completed_at, o.remark, o.accepted_by,
                           o.web_user_id as username, s.nickname as accepted_by_nickname
                    FROM orders o 
                    LEFT JOIN sellers s ON o.accepted_by = s.telegram_id::text
                    WHERE o.user_id = %s
                    ORDER BY o.id DESC LIMIT %s OFFSET %s
                """, (user_id, limit, offset), fetch=True)
            
            # 转换为字典格式
            orders_list = []
            for order in orders:
                orders_list.append({
                    'id': order[0],
                    'account': order[1],
                    'package': order[2],
                    'status': order[3],
                    'status_text': STATUS_TEXT_ZH.get(order[3], order[3]),
                    'created_at': order[4].isoformat() if order[4] else None,
                    'accepted_at': order[5].isoformat() if order[5] else None,
                    'completed_at': order[6].isoformat() if order[6] else None,
                    'remark': order[7],
                    'accepted_by': order[8],
                    'username': order[9],
                    'accepted_by_nickname': order[10],
                    'confirm_status': 'pending'  # 默认确认状态
                })
            
            return jsonify({
                'success': True,
                'orders': orders_list,
                'timestamp': datetime.now().timestamp()
            })
            
        except Exception as e:
            logger.error(f"获取订单列表失败: {str(e)}")
            return jsonify({'success': False, 'message': '获取订单失败'}), 500
    
    @app.route('/api/today-stats')
    def get_today_stats():
        """获取今日统计信息"""
        try:
            today = datetime.now().date()
            
            # 检查用户是否登录
            user_id = session.get('user_id')
            
            if not user_id:
                # 未登录用户看到全局统计（但不显示个人统计）
                stats = execute_query("""
                    SELECT 
                        COUNT(*) as total_orders,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_orders,
                        COUNT(CASE WHEN status = 'submitted' THEN 1 END) as pending_orders
                    FROM orders 
                    WHERE DATE(created_at) = %s
                """, (today,), fetch=True)
                
                return jsonify({
                    'success': True,
                    'all_today_confirmed': stats[0][1] if stats else 0,
                    'user_today_confirmed': 0,  # 未登录用户个人统计为0
                    'total_orders': stats[0][0] if stats else 0,
                    'pending_orders': stats[0][2] if stats else 0,
                    'message': '请登录查看个人统计'
                })
            
            # 获取今日订单统计
            if session.get('role') == 'admin':
                # 管理员看到所有统计
                stats = execute_query("""
                    SELECT 
                        COUNT(*) as total_orders,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_orders,
                        COUNT(CASE WHEN status = 'submitted' THEN 1 END) as pending_orders
                    FROM orders 
                    WHERE DATE(created_at) = %s
                """, (today,), fetch=True)
                
                all_today_confirmed = stats[0][1] if stats else 0
                user_today_confirmed = all_today_confirmed
            else:
                # 普通用户只看自己的统计
                stats = execute_query("""
                    SELECT 
                        COUNT(*) as total_orders,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_orders,
                        COUNT(CASE WHEN status = 'submitted' THEN 1 END) as pending_orders
                    FROM orders 
                    WHERE DATE(created_at) = %s AND user_id = %s
                """, (today, user_id), fetch=True)
                
                user_today_confirmed = stats[0][1] if stats else 0
                # 普通用户也能看到全局统计
                global_stats = execute_query("""
                    SELECT COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_orders
                    FROM orders 
                    WHERE DATE(created_at) = %s
                """, (today,), fetch=True)
                all_today_confirmed = global_stats[0][0] if global_stats else 0
            
            return jsonify({
                'success': True,
                'all_today_confirmed': all_today_confirmed,
                'user_today_confirmed': user_today_confirmed,
                'total_orders': stats[0][0] if stats else 0,
                'pending_orders': stats[0][2] if stats else 0
            })
            
        except Exception as e:
            logger.error(f"获取今日统计失败: {str(e)}")
            return jsonify({'success': False, 'message': '获取统计失败'}), 500
    
    @app.route('/api/all-sellers')
    def get_all_sellers_api():
        """获取所有卖家列表"""
        try:
            sellers = execute_query("""
                SELECT telegram_id, nickname, username, first_name, is_active, last_active_at
                FROM sellers 
                ORDER BY added_at DESC
            """, fetch=True)
            
            sellers_list = []
            for seller in sellers:
                display_name = seller[1] or seller[3] or f"Seller {seller[0]}"
                sellers_list.append({
                    'id': seller[0],
                    'name': display_name,
                    'username': seller[2],
                    'is_active': seller[4],
                    'last_active_at': seller[5].isoformat() if seller[5] else None
                })
            
            return jsonify({
                'success': True,
                'sellers': sellers_list
            })
            
        except Exception as e:
            logger.error(f"获取所有卖家失败: {str(e)}")
            return jsonify({'success': False, 'message': '获取卖家列表失败'}), 500
    
    @app.route('/api/participating-sellers')
    def get_participating_sellers():
        """获取参与分流的卖家列表"""
        try:
            sellers = execute_query("""
                SELECT telegram_id, nickname, username, first_name, is_active, last_active_at
                FROM sellers 
                WHERE is_active = TRUE
                ORDER BY last_active_at DESC NULLS LAST
            """, fetch=True)
            
            sellers_list = []
            for seller in sellers:
                display_name = seller[1] or seller[3] or f"Seller {seller[0]}"
                sellers_list.append({
                    'id': seller[0],
                    'name': display_name,
                    'username': seller[2],
                    'is_active': seller[4],
                    'last_active_at': seller[5].isoformat() if seller[5] else None
                })
            
            return jsonify({
                'success': True,
                'sellers': sellers_list
            })
            
        except Exception as e:
            logger.error(f"获取参与分流卖家失败: {str(e)}")
            return jsonify({'success': False, 'message': '获取卖家列表失败'}), 500
    
    @app.route('/api/smart-remark', methods=['POST'])
    def smart_remark():
        """智能备注建议"""
        try:
            data = request.get_json()
            remark = data.get('remark', '') if data else ''
            
            # 这里可以添加智能备注逻辑
            # 目前返回简单的建议
            suggestions = []
            if not remark or len(remark.strip()) < 3:
                suggestions = [
                    "请确保账号信息正确",
                    "充值后请及时确认",
                    "如有问题请联系客服"
                ]
            
            return jsonify({
                'success': True,
                'suggestions': suggestions,
                'show_modal': len(suggestions) > 0
            })
            
        except Exception as e:
            logger.error(f"智能备注处理失败: {str(e)}")
            return jsonify({'success': False, 'message': '处理失败'}), 500
    
    @app.route('/api/check-duplicate-remark', methods=['POST'])
    def check_duplicate_remark():
        """检查备注重复"""
        try:
            data = request.get_json()
            remark = data.get('remark', '') if data else ''
            
            if not remark or len(remark.strip()) < 3:
                return jsonify({'success': True, 'duplicate': False})
            
            # 检查今日是否有相同备注
            today = datetime.now().date()
            duplicates = execute_query("""
                SELECT COUNT(*) FROM orders 
                WHERE remark = %s AND DATE(created_at) = %s
            """, (remark, today), fetch=True)
            
            is_duplicate = duplicates and duplicates[0][0] > 0
            
            return jsonify({
                'success': True,
                'duplicate': is_duplicate
            })
            
        except Exception as e:
            logger.error(f"检查备注重复失败: {str(e)}")
            return jsonify({'success': False, 'message': '检查失败'}), 500
    
    @app.route('/api/active-sellers')
    def get_active_sellers():
        """获取活跃卖家列表"""
        try:
            sellers = execute_query("""
                SELECT telegram_id, nickname, username, first_name, is_active, last_active_at
                FROM sellers 
                WHERE is_active = TRUE 
                ORDER BY last_active_at DESC NULLS LAST
            """, fetch=True)
            
            sellers_list = []
            for seller in sellers:
                display_name = seller[1] or seller[3] or f"Seller {seller[0]}"
                sellers_list.append({
                    'id': seller[0],
                    'name': display_name,
                    'username': seller[2],
                    'last_active_at': seller[5].isoformat() if seller[5] else None,
                    'active_status': 'active' if seller[4] else 'inactive'
                })
            
            return jsonify({
                'success': True,
                'sellers': sellers_list
            })
            
        except Exception as e:
            logger.error(f"获取活跃卖家失败: {str(e)}")
            return jsonify({'success': False, 'message': '获取卖家列表失败'}), 500
    
    @app.route('/api/upload', methods=['POST'])
    @login_required
    def upload_file():
        """文件上传接口"""
        try:
            if 'file' not in request.files:
                return jsonify({'success': False, 'message': '没有文件'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'message': '没有选择文件'}), 400
            
            if file and allowed_file(file.filename):
                # 生成唯一文件名
                filename = secure_filename(file.filename)
                name, ext = os.path.splitext(filename)
                unique_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
                
                # 确保上传目录存在
                upload_path = os.path.join(app.root_path, UPLOAD_FOLDER)
                os.makedirs(upload_path, exist_ok=True)
                
                # 保存文件
                file_path = os.path.join(upload_path, unique_filename)
                file.save(file_path)
                
                # 返回文件URL
                file_url = f"/{UPLOAD_FOLDER}/{unique_filename}"
                
                return jsonify({
                    'success': True,
                    'file_url': file_url,
                    'filename': unique_filename
                })
            else:
                return jsonify({'success': False, 'message': '不支持的文件类型'}), 400
                
        except Exception as e:
            logger.error(f"文件上传失败: {str(e)}")
            return jsonify({'success': False, 'message': '文件上传失败'}), 500
    
    # ==================== 管理员API ====================
    
    @app.route('/admin/api/sellers', methods=['GET'])
    @admin_required
    def admin_get_sellers():
        """管理员获取所有卖家"""
        try:
            sellers = execute_query("""
                SELECT telegram_id, nickname, username, first_name, is_active, 
                       added_at, last_active_at, added_by
                FROM sellers 
                ORDER BY added_at DESC
            """, fetch=True)
            
            sellers_list = []
            for seller in sellers:
                sellers_list.append({
                    'telegram_id': seller[0],
                    'nickname': seller[1],
                    'username': seller[2],
                    'first_name': seller[3],
                    'is_active': seller[4],
                    'added_at': seller[5].isoformat() if seller[5] else None,
                    'last_active_at': seller[6].isoformat() if seller[6] else None,
                    'added_by': seller[7]
                })
            
            return jsonify(sellers_list)
            
        except Exception as e:
            logger.error(f"获取卖家列表失败: {str(e)}")
            return jsonify({'error': '获取卖家列表失败'}), 500
    
    @app.route('/admin/api/sellers', methods=['POST'])
    @admin_required
    def admin_add_seller():
        """管理员添加卖家"""
        try:
            data = request.get_json()
            telegram_id = data.get('telegram_id')
            username = data.get('username', '')
            first_name = data.get('first_name', '')
            nickname = data.get('nickname', '')
            
            if not telegram_id:
                return jsonify({'error': 'Telegram ID不能为空'}), 400
            
            # 检查是否已存在
            existing = execute_query(
                "SELECT telegram_id FROM sellers WHERE telegram_id = %s",
                (telegram_id,), fetch=True
            )
            
            if existing:
                return jsonify({'error': '该卖家已存在'}), 400
            
            # 添加卖家
            added_by = session.get('username', 'admin')
            execute_query("""
                INSERT INTO sellers (telegram_id, username, first_name, nickname, added_by, added_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (telegram_id, username, first_name, nickname, added_by, datetime.now()))
            
            return jsonify({'success': True, 'message': '卖家添加成功'})
            
        except Exception as e:
            logger.error(f"添加卖家失败: {str(e)}")
            return jsonify({'error': '添加卖家失败'}), 500
    
    @app.route('/admin/api/sellers/<telegram_id>', methods=['PUT'])
    @admin_required
    def admin_update_seller(telegram_id):
        """管理员更新卖家信息"""
        try:
            data = request.get_json()
            nickname = data.get('nickname')
            max_concurrent_orders = data.get('max_concurrent_orders')
            
            if nickname is not None:
                execute_query(
                    "UPDATE sellers SET nickname = %s WHERE telegram_id = %s",
                    (nickname, telegram_id)
                )
            
            if max_concurrent_orders is not None:
                # 如果需要更新最大并发订单数，可以添加相应字段和逻辑
                pass
            
            return jsonify({'success': True, 'message': '卖家信息更新成功'})
            
        except Exception as e:
            logger.error(f"更新卖家失败: {str(e)}")
            return jsonify({'error': '更新卖家失败'}), 500
    
    @app.route('/admin/api/sellers/<telegram_id>/toggle', methods=['POST'])
    @admin_required
    def admin_toggle_seller(telegram_id):
        """管理员切换卖家状态"""
        try:
            execute_query(
                "UPDATE sellers SET is_active = NOT is_active WHERE telegram_id = %s",
                (telegram_id,)
            )
            return jsonify({'success': True, 'message': '卖家状态已更新'})
            
        except Exception as e:
            logger.error(f"切换卖家状态失败: {str(e)}")
            return jsonify({'error': '操作失败'}), 500
    
    @app.route('/admin/api/sellers/<telegram_id>/toggle_distribution', methods=['POST'])
    @admin_required
    def admin_toggle_seller_distribution(telegram_id):
        """管理员切换卖家分流状态"""
        try:
            # 这里可以添加分流状态的逻辑
            # 暂时使用 is_active 字段
            execute_query(
                "UPDATE sellers SET is_active = NOT is_active WHERE telegram_id = %s",
                (telegram_id,)
            )
            return jsonify({'success': True, 'message': '分流状态已更新'})
            
        except Exception as e:
            logger.error(f"切换分流状态失败: {str(e)}")
            return jsonify({'error': '操作失败'}), 500
    
    @app.route('/admin/api/users', methods=['GET'])
    @admin_required
    def admin_get_users():
        """管理员获取用户列表"""
        users = get_all_users()
        return jsonify({'success': True, 'users': users})
    
    @app.route('/admin/api/users/<int:user_id>', methods=['DELETE'])
    @admin_required
    def admin_delete_user(user_id):
        """管理员删除用户"""
        if user_id == session.get('user_id'):
            return jsonify({'error': '不能删除自己的账户'}), 400
        
        success, message = delete_user(user_id)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'error': message}), 500
    
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
        if user_id == session.get('user_id'):
            return jsonify({'success': False, 'message': '不能删除自己的账户'}), 400
        
        success, message = delete_user(user_id)
        return jsonify({'success': success, 'message': message}) 
    
    @app.route('/api/user-stats')
    @login_required
    def get_user_stats():
        """获取当前用户的订单统计"""
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'success': False, 'message': '请先登录'}), 401
            
            # 获取用户订单统计
            stats = execute_query("""
                SELECT 
                    COUNT(*) as total_orders,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_orders,
                    COUNT(CASE WHEN status = 'submitted' THEN 1 END) as pending_orders
                FROM orders 
                WHERE user_id = %s
            """, (user_id,), fetch=True)
            
            result = {
                'success': True,
                'total_orders': stats[0][0] if stats else 0,
                'completed_orders': stats[0][1] if stats else 0,
                'pending_orders': stats[0][2] if stats else 0
            }
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"获取用户统计失败: {str(e)}")
            return jsonify({'success': False, 'message': '获取统计失败'}), 500 