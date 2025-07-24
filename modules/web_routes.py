import os
import logging
from functools import wraps
from datetime import datetime
from flask import request, render_template, jsonify, session, redirect, url_for, send_from_directory
from modules.constants import STATUS, STATUS_TEXT_ZH, DATABASE_URL, CONFIRM_STATUS, CONFIRM_STATUS_TEXT_ZH
from modules.database import (
    execute_query, hash_password, get_all_sellers, get_active_sellers, toggle_seller_status, 
    remove_seller, update_seller_nickname, create_order_with_deduction_atomic,
    add_seller
)

logger = logging.getLogger(__name__)

# 登录装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def register_routes(app, notification_queue):
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            if not username or not password:
                return render_template('login.html', error='请填写用户名和密码')
            hashed_password = hash_password(password)
            user = execute_query("SELECT id, username, is_admin FROM users WHERE username=? AND password_hash=?", (username, hashed_password), fetch=True)
            if user:
                user_id, username, is_admin = user[0]
                session['user_id'] = user_id
                session['username'] = username
                session['is_admin'] = is_admin
                execute_query("UPDATE users SET last_login=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
                return redirect(url_for('index'))
            else:
                return render_template('login.html', error='用户名或密码错误')
        return render_template('login.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            confirm_password = request.form.get('password_confirm')
            if not username or not password or not confirm_password:
                return render_template('register.html', error='请填写所有字段')
            if password != confirm_password:
                return render_template('register.html', error='两次密码输入不一致')
            existing_user = execute_query("SELECT id FROM users WHERE username=?", (username,), fetch=True)
            if existing_user:
                return render_template('register.html', error='用户名已存在')
            hashed_password = hash_password(password)
            execute_query("""
                INSERT INTO users (username, password_hash, is_admin, created_at) 
                VALUES (?, ?, 0, ?)
            """, (username, hashed_password, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            return redirect(url_for('login'))
        return render_template('register.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/', methods=['GET'])
    @login_required
    def index():
        try:
            orders = execute_query("SELECT id, account, package, status, created_at FROM orders ORDER BY id DESC LIMIT 5", fetch=True)
            return render_template('index.html', orders=orders, username=session.get('username'), is_admin=session.get('is_admin'))
        except Exception as e:
            return render_template('index.html', error='获取订单失败', username=session.get('username'), is_admin=session.get('is_admin'))

    @app.route('/', methods=['POST'])
    @login_required
    def create_order():
        if 'qr_code' in request.files and request.files['qr_code'].filename != '':
            qr_code = request.files['qr_code']
        else:
            return jsonify({"success": False, "error": "请上传二维码图片"}), 400
        import uuid, imghdr, shutil
            temp_path = os.path.join('static', 'temp_upload.png')
            qr_code.save(temp_path)
            img_type = imghdr.what(temp_path)
            if not img_type:
            os.remove(temp_path)
                return jsonify({"success": False, "error": "请上传有效的图片文件"}), 400
            file_ext = f".{img_type}" if img_type else ".png"
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            timestamp = datetime.now().strftime("%Y%m%d")
            save_path = os.path.join('static', 'uploads', timestamp)
            if not os.path.exists(save_path):
                os.makedirs(save_path, exist_ok=True)
            file_path = os.path.join(save_path, unique_filename)
            shutil.copy2(temp_path, file_path)
            os.chmod(file_path, 0o644)
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                return jsonify({"success": False, "error": "图片保存失败，请重试"}), 500
        account = file_path
        password = ""
        package = request.form.get('package', '12')
        remark = request.form.get('remark', '')
            user_id = session.get('user_id')
            username = session.get('username')
                result = create_order_with_deduction_atomic(account, password, package, remark, username, user_id)
                if isinstance(result, tuple):
                    success, message = result[0], result[1]
                else:
                    success, message = result, ''
            if not success:
            return jsonify({"success": False, "error": message}), 400
        return jsonify({"success": True, "message": '订单已提交成功！'})

    @app.route('/orders/recent')
    @login_required
    def orders_recent():
            is_admin = session.get('is_admin')
            user_id = session.get('user_id')
                if is_admin:
            orders = execute_query("SELECT id, account, package, status, created_at FROM orders ORDER BY id DESC LIMIT 50", fetch=True)
                else:
            orders = execute_query("SELECT id, account, package, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 50", (user_id,), fetch=True)
        return jsonify({"success": True, "orders": orders})

    @app.route('/orders/confirm/<int:oid>', methods=['POST'])
    @login_required
    def confirm_order(oid):
        user_id = session.get('user_id')
        order = execute_query("SELECT status, user_id FROM orders WHERE id=?", (oid,), fetch=True)
        if not order:
            return jsonify({"error": "订单不存在"}), 404
        status, order_user_id = order[0]
        if order_user_id != user_id and not session.get('is_admin'):
            return jsonify({"error": "您无权确认该订单"}), 403
        execute_query("UPDATE orders SET status=?, completed_at=? WHERE id=?", (STATUS['COMPLETED'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), oid))
        return jsonify({"success": True})

    # 后台管理：订单和卖家管理
    @app.route('/admin')
    @login_required
    def admin_dashboard():
        if not session.get('is_admin'):
            return redirect(url_for('index'))
        return render_template('admin.html')

    @app.route('/admin/api/orders')
    @login_required
    def admin_api_orders():
        if not session.get('is_admin'):
            return jsonify({"error": "权限不足"}), 403
        orders = execute_query("SELECT id, account, package, status, created_at FROM orders ORDER BY id DESC LIMIT 100", fetch=True)
        return jsonify({"orders": orders})
        
    @app.route('/admin/api/sellers', methods=['GET'])
    @login_required
    def admin_api_get_sellers():
        if not session.get('is_admin'):
            return jsonify({"error": "权限不足"}), 403
        sellers = get_all_sellers()
        return jsonify({"sellers": sellers})

    @app.route('/admin/api/sellers', methods=['POST'])
    @login_required
    def admin_api_add_seller():
        if not session.get('is_admin'):
            return jsonify({"error": "权限不足"}), 403
        data = request.json
        telegram_id = data.get('telegram_id')
        add_seller(telegram_id, data.get('username'), data.get('first_name'), data.get('nickname'), session.get('username'))
        return jsonify({"success": True})

    @app.route('/admin/api/sellers/<int:telegram_id>/toggle', methods=['POST'])
    @login_required
    def admin_api_toggle_seller(telegram_id):
        if not session.get('is_admin'):
            return jsonify({"error": "权限不足"}), 403
        toggle_seller_status(telegram_id)
        return jsonify({"success": True})

    @app.route('/admin/api/sellers/<int:telegram_id>', methods=['DELETE'])
    @login_required
    def admin_api_remove_seller(telegram_id):
        if not session.get('is_admin'):
            return jsonify({"error": "权限不足"}), 403
        remove_seller(telegram_id)
        return jsonify({"success": True})

    @app.route('/admin/api/sellers/<int:telegram_id>/nickname', methods=['POST'])
    @login_required
    def admin_api_update_seller_nickname(telegram_id):
        if not session.get('is_admin'):
            return jsonify({"error": "权限不足"}), 403
            data = request.json
        nickname = data.get('nickname')
                update_seller_nickname(telegram_id, nickname)
            return jsonify({"success": True})

    @app.route('/static/uploads/<path:filename>')
    def serve_uploads(filename):
        return send_from_directory('static/uploads', filename)