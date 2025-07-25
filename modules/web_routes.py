from flask import Flask, request, jsonify, render_template
import logging
from modules.database import execute_query, get_all_sellers
from modules.constants import STATUS_TEXT_ZH

logger = logging.getLogger(__name__)

def register_routes(app: Flask):
    """注册所有Web路由"""
    
    @app.route('/')
    def index():
        """主页"""
        return render_template('index.html')
    
    @app.route('/orders')
    def orders():
        """订单管理页面"""
        orders = execute_query(
            "SELECT id, account, package, status, created_at, remark, user_id FROM orders ORDER BY id DESC LIMIT 50",
            fetch=True
        )
        return render_template('orders.html', orders=orders, status_text=STATUS_TEXT_ZH)
    
    @app.route('/sellers')
    def sellers():
        """卖家管理页面"""
        sellers = get_all_sellers()
        return render_template('sellers.html', sellers=sellers) 