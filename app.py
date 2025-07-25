import os
import threading
import logging
import sys
from flask import Flask, request, jsonify, send_file, flash
import traceback

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 导入自定义模块
from modules.database import init_db, check_db_connection
from modules.telegram_bot import run_bot, process_telegram_update
from modules.web_routes import register_routes

# ===== Flask 应用 =====
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'secret_key')

# 确保静态文件目录存在
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
uploads_dir = os.path.join(static_dir, 'uploads')
if not os.path.exists(uploads_dir):
    try:
        os.makedirs(uploads_dir)
        logger.info(f"创建上传目录: {uploads_dir}")
    except Exception as e:
        logger.error(f"创建上传目录失败: {str(e)}")

# 注册Web路由
register_routes(app)

# 添加一个直接访问图片的路由
@app.route('/<path:filepath>')
def serve_file(filepath):
    """提供直接访问文件的路由，主要用于TG机器人访问图片"""
    if 'static/uploads' in filepath:
        try:
            parts = filepath.split('static/uploads/')
            if len(parts) > 1:
                filename = parts[1]
                return app.send_static_file(f'uploads/{filename}')
        except Exception as e:
            logger.error(f"访问文件 {filepath} 时出错: {str(e)}")
    return "File not found", 404

# 添加Telegram webhook路由
@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    """处理来自Telegram的webhook请求"""
    try:
        update_data = request.get_json()
        logger.info(f"收到Telegram webhook更新")
        
        # 在单独的线程中处理更新
        threading.Thread(
            target=process_telegram_update,
            args=(update_data,),
            daemon=True
        ).start()
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"处理Telegram webhook时出错: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """处理所有未捕获的异常"""
    logger.error(f"未捕获的异常: {str(e)}")
    return jsonify({"error": str(e)}), 500

# ===== 主程序 =====
if __name__ == "__main__":
    # 启动时检查数据库连接
    check_db_connection()

    # 初始化数据库
    logger.info("正在初始化数据库...")
    init_db()
    logger.info("数据库初始化完成")
    
    # 启动 Bot 线程
    logger.info("正在启动Telegram机器人...")
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Telegram机器人线程已启动")
    
    # 启动 Flask
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"正在启动Flask服务器，端口：{port}...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)