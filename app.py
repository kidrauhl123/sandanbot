import os
import threading
import logging
import time
import queue
import sys
import atexit
import signal
import json
import traceback
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, send_file, g
import sqlite3
import shutil
import asyncio
import datetime

# 根据环境变量确定是否为生产环境
is_production = os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('PRODUCTION')

# 日志配置
logging.basicConfig(
    level=logging.INFO if is_production else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 导入自定义模块
from modules.database import init_db, execute_query
from modules.telegram_bot import run_bot, process_telegram_update
from modules.web_routes import register_routes
from modules.constants import sync_env_sellers_to_db

# 创建一个线程安全的队列用于在Flask和Telegram机器人之间通信
# 这个队列将会在启动Telegram机器人时被替换为机器人内部创建的队列
notification_queue = queue.Queue()

# 添加一个全局函数来获取通知队列
def get_notification_queue():
    """获取全局通知队列"""
    return notification_queue

# 锁目录路径
lock_dir = 'bot.lock'

# 清理锁目录和数据库 journal 文件的函数
def cleanup_resources():
    """清理应用锁目录和数据库 journal 文件。"""
    # 清理应用锁目录
    if os.path.exists(lock_dir):
        try:
            if os.path.isdir(lock_dir):
                os.rmdir(lock_dir)
                logger.info(f"已清理锁目录: {lock_dir}")
            else:
                os.remove(lock_dir) # 如果意外地成了文件
                logger.info(f"已清理锁文件: {lock_dir}")
        except Exception as e:
            logger.error(f"清理锁目录时出错: {str(e)}", exc_info=True)

    # 清理数据库 journal 文件
    try:
        journal_path = "orders.db-journal"
        if os.path.exists(journal_path):
            os.remove(journal_path)
            logger.info(f"已清理残留的 journal 文件: {journal_path}")
    except Exception as e:
        logger.error(f"清理 journal 文件时出错: {str(e)}", exc_info=True)

# 信号处理函数
def signal_handler(sig, frame):
    logger.info(f"收到信号 {sig}，正在清理资源...")
    cleanup_resources()
    sys.exit(0)

# 注册信号处理器和退出钩子
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
atexit.register(cleanup_resources)

# ===== Flask 应用 =====
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'secret_' + str(time.time()))
app.config['DEBUG'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True

# 确保静态文件目录存在
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
uploads_dir = os.path.join(static_dir, 'uploads')
if not os.path.exists(uploads_dir):
    try:
        os.makedirs(uploads_dir)
        logger.info(f"创建上传目录: {uploads_dir}")
    except Exception as e:
        logger.error(f"创建上传目录失败: {str(e)}", exc_info=True)

# 在应用启动时检查目录权限和结构
@app.before_first_request
def check_directories():
    """在首次请求之前检查必要的目录结构和权限"""
    try:
        # 确认静态文件目录存在并可写
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
            logger.info(f"创建了静态文件目录: {static_dir}")
        
        # 确认上传目录存在并可写
        uploads_dir = os.path.join(static_dir, 'uploads')
        if not os.path.exists(uploads_dir):
            os.makedirs(uploads_dir)
            logger.info(f"创建了上传目录: {uploads_dir}")
            
        # 确认每日上传目录存在（按日期分类）
        import datetime
        today = datetime.datetime.now().strftime("%Y%m%d")
        today_dir = os.path.join(uploads_dir, today)
        if not os.path.exists(today_dir):
            os.makedirs(today_dir)
            logger.info(f"创建了今日上传目录: {today_dir}")
            
        # 测试目录写入权限
        test_file = os.path.join(today_dir, ".test_write_permission")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            logger.info(f"目录权限测试成功: {today_dir}")
        except Exception as e:
            logger.error(f"目录 {today_dir} 没有写入权限: {str(e)}")
            
        # 记录应用状态信息
        logger.info(f"应用静态文件配置: app.static_folder={app.static_folder}, app.static_url_path={app.static_url_path}")
        logger.info(f"当前工作目录: {os.getcwd()}")
            
    except Exception as e:
        logger.error(f"检查目录结构时发生错误: {str(e)}", exc_info=True)

# 启动缓存预热器
def start_cache_warmer_if_enabled():
    """如果启用了缓存预热，则启动预热器"""
    try:
        # 导入缓存预热器
        from modules.cache_warmer import start_cache_warmer
        
        # 判断是否启用
        import os
        enabled = os.getenv('CACHE_WARMER_ENABLED', 'True').lower() == 'true'
        
        if enabled:
            logger.info("启动缓存预热器...")
            start_cache_warmer()
            logger.info("缓存预热器已启动")
    except ImportError:
        logger.warning("缓存预热器模块不可用")
    except Exception as e:
        logger.error(f"启动缓存预热器时出错: {str(e)}")

# 应用启动完成后的操作
@app.before_first_request
def on_startup():
    # 检查必要的目录
    check_directories()
    # 启动缓存预热器
    start_cache_warmer_if_enabled()
    logger.info("应用初始化完成")

# 添加紧急模式参数到模板上下文
@app.context_processor
def inject_emergency_mode():
    """在所有模板中注入紧急模式标志"""
    import os
    emergency_mode = os.getenv('EMERGENCY_MODE', 'false').lower() == 'true'
    return {
        'emergency_mode': emergency_mode
    }

# 添加调试路由
@app.route('/debug/dirs')
def debug_dirs():
    """显示应用的目录结构信息，用于调试"""
    try:
        import sys
        import platform
        
        # 收集系统和环境信息
        info = {
            "app_config": {
                "static_folder": app.static_folder,
                "static_url_path": app.static_url_path,
                "instance_path": app.instance_path,
                "template_folder": app.template_folder,
                "debug": app.debug,
            },
            "dirs": {
                "current_dir": os.getcwd(),
                "app_dir": os.path.dirname(os.path.abspath(__file__)),
                "static_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'),
                "uploads_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads'),
            },
            "sys_info": {
                "platform": platform.platform(),
                "python": sys.version,
                "env": {k: v for k, v in os.environ.items() if k.startswith(('FLASK_', 'APP_', 'DATABASE_', 'PORT'))}
            }
        }
        
        # 检查目录是否存在
        for name, path in info["dirs"].items():
            info["dirs"][f"{name}_exists"] = os.path.exists(path)
            if os.path.exists(path):
                try:
                    info["dirs"][f"{name}_writable"] = os.access(path, os.W_OK)
                except:
                    info["dirs"][f"{name}_writable"] = False
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"生成调试信息时出错: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# 注册Web路由，并将队列传递给它
register_routes(app, notification_queue)

# 添加静态文件路由，确保图片URLs可以访问
@app.route('/static/uploads/<path:filename>')
def serve_uploads(filename):
    # 构建正确的路径，不使用app.send_static_file，而是直接从文件系统路径发送文件
    import os
    from flask import send_from_directory
    
    uploads_dir = os.path.join(app.static_folder, 'uploads')
    # 确保路径存在
    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir, exist_ok=True)
    
    try:
        return send_from_directory(uploads_dir, filename)
    except Exception as e:
        logger.error(f"访问文件 uploads/{filename} 时出错: {str(e)}")
        return "File not found", 404

# 添加一个直接访问图片的路由，支持完整路径
@app.route('/<path:filepath>')
def serve_file(filepath):
    """提供直接访问文件的路由，主要用于TG机器人访问图片"""
    if 'static/uploads' in filepath:
        try:
            # 从完整路径中提取相对路径
            from flask import send_from_directory
            import os
            
            parts = filepath.split('static/uploads/')
            if len(parts) > 1:
                filename = parts[1]
                uploads_dir = os.path.join(app.static_folder, 'uploads')
                return send_from_directory(uploads_dir, filename)
        except Exception as e:
            logger.error(f"访问文件 {filepath} 时出错: {str(e)}")
    
    # 如果不是上传文件路径，返回404
    return "File not found", 404

# 添加一个专门的图片查看页面
@app.route('/view-image/<path:filepath>')
def view_image(filepath):
    """提供一个专门的图片查看页面"""
    try:
        # 构建完整的文件路径
        import os
        from flask import send_file
        import mimetypes
        
        # 检查文件路径是否含有static/uploads前缀
        if 'static/uploads' in filepath:
            # 提取uploads后面的部分
            parts = filepath.split('static/uploads/')
            if len(parts) > 1:
                rel_path = parts[1]
                full_path = os.path.join(app.static_folder, 'uploads', rel_path)
        else:
            # 如果没有static/uploads前缀，尝试当作相对路径处理
            full_path = filepath
            if not os.path.exists(full_path):
                # 尝试添加static前缀
                if not full_path.startswith('static/'):
                    full_path = os.path.join('static', filepath)
        
        if os.path.exists(full_path) and os.path.isfile(full_path):
            # 确定MIME类型
            mime_type = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
            
            # 如果是图片，返回HTML页面显示图片
            if mime_type.startswith('image/'):
                # 获取文件的相对URL
                file_url = '/static/uploads/' + os.path.relpath(full_path, os.path.join(app.static_folder, 'uploads')) if 'uploads' in full_path else '/' + filepath
                
                # 返回HTML页面
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>YouTube QR Code</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; text-align: center; }}
                        .image-container {{ max-width: 100%; margin: 0 auto; }}
                        img {{ max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; padding: 5px; }}
                        h1 {{ color: #333; }}
                        .info {{ margin: 20px 0; color: #666; }}
                    </style>
                </head>
                <body>
                    <h1>YouTube QR Code</h1>
                    <div class="image-container">
                        <img src="{file_url}" alt="YouTube QR Code">
                    </div>
                    <div class="info">
                        <p>请扫描上方二维码</p>
                    </div>
                </body>
                </html>
                """
                return html
            else:
                # 如果不是图片，直接返回文件
                return send_file(full_path, mimetype=mime_type)
        else:
            logger.error(f"找不到文件: {full_path}")
            return "File not found", 404
    except Exception as e:
        logger.error(f"查看图片 {filepath} 时出错: {str(e)}", exc_info=True)
        return f"Error viewing image: {str(e)}", 500

# 添加Telegram webhook路由
@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    """处理来自Telegram的webhook请求"""
    try:
        logger.info("收到Telegram webhook请求")
        print("DEBUG: 收到Telegram webhook请求")
        # 获取原始请求体，便于调试
        raw_data = request.data
        logger.info(f"Webhook原始请求体: {raw_data}")
        try:
            update_data = request.get_json(force=True, silent=False)
        except Exception as json_err:
            logger.error(f"解析JSON失败: {str(json_err)}")
            return jsonify({"status": "error", "message": f"JSON解析失败: {str(json_err)}"}), 400
        logger.info(f"Webhook解析后数据: {update_data}")
        print(f"DEBUG: Webhook解析后数据: {update_data}")
        # 在单独的线程中处理更新，避免阻塞Flask响应
        threading.Thread(
            target=process_telegram_update,
            args=(update_data, notification_queue),
            daemon=True
        ).start()
        # 立即返回响应，避免Telegram超时
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"处理Telegram webhook时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 处理Telegram webhook时出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """处理所有未捕获的异常"""
    logger.error(f"未捕获的异常: {str(e)}", exc_info=True)
    print(f"ERROR: 未捕获的异常: {str(e)}")
    traceback.print_exc()
    return jsonify({"error": str(e)}), 500

# 健康检查端点
@app.route('/health')
def health_check():
    """健康检查端点，用于平台监控"""
    try:
        # 尝试连接数据库
        from modules.database import test_db_connection
        db_ok = test_db_connection()
        
        health_status = {
            "status": "healthy" if db_ok else "degraded",
            "timestamp": datetime.datetime.now().isoformat(),
            "version": os.environ.get('APP_VERSION', '1.0.0'),
            "db_connection": "ok" if db_ok else "error"
        }
        
        status_code = 200 if db_ok else 500
        return jsonify(health_status), status_code
    except Exception as e:
        logger.error(f"健康检查失败: {str(e)}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        }), 500

# 根路径响应
@app.route('/')
def root():
    """根路径响应，确保基本路径可访问"""
    if 'user_id' in session:
        return redirect('/index')
    else:
        return redirect('/login')

# ===== 主程序 =====
if __name__ == "__main__":
    # 在启动前先尝试清理可能存在的锁文件和目录
    cleanup_resources()
            
    # 使用锁目录确保只有一个实例运行
    try:
        # 先检查锁目录是否存在，如果存在则尝试删除（可能是之前的实例异常退出）
        if os.path.exists(lock_dir):
            try:
                if os.path.isdir(lock_dir):
                    os.rmdir(lock_dir)
                else:
                    os.remove(lock_dir)
                logger.info(f"清理了可能残留的锁: {lock_dir}")
            except Exception as e:
                logger.error(f"清理残留锁失败: {str(e)}")
                # 如果无法清理锁，检查是否有进程持有锁
                import platform
                if platform.system() == 'Windows':
                    logger.error("在Windows上无法检查进程锁，假定锁无效并继续")
                else:
                    # 在Linux/Unix上尝试通过lsof检查是否有进程持有锁
                    try:
                        import subprocess
                        result = subprocess.run(['lsof', '+D', lock_dir], capture_output=True, text=True)
                        if result.stdout.strip():
                            logger.error(f"有进程正在使用锁目录，程序退出: {result.stdout}")
                            sys.exit(1)
                        else:
                            logger.info("锁目录没有被其他进程使用，继续执行")
                    except Exception as e:
                        logger.error(f"检查锁目录使用情况失败: {str(e)}")
                        
        # 创建新的锁目录
        os.mkdir(lock_dir)
        logger.info("成功获取锁，启动主程序。")
    except FileExistsError:
        logger.error("锁目录已存在，另一个实例可能正在运行。程序退出。")
        sys.exit(1)
    except Exception as e:
        logger.error(f"创建锁目录时发生未知错误: {e}")
        sys.exit(1)

    # 初始化数据库
    logger.info("正在初始化数据库...")
    init_db()
    logger.info("数据库初始化完成")
    
    # 同步环境变量中的卖家到数据库
    logger.info("同步环境变量卖家到数据库...")
    sync_env_sellers_to_db()
    logger.info("环境变量卖家同步完成")
    
    # 导入TG机器人模块并启动
    try:
        from modules.tgbot import start_bot
        
        # 直接启动TG机器人，内部已经创建了线程
        # 我们使用nonlocal关键字来表明我们要修改全局的notification_queue
        # 但在Python中，不能在函数内使用nonlocal来访问全局变量，所以这里直接赋值
        notification_queue = start_bot()  # start_bot会返回创建的队列
        logger.info("Telegram机器人已启动")
    except Exception as e:
        logger.error(f"启动TG机器人失败: {str(e)}", exc_info=True)
    
    # 禁用紧急模式
    os.environ['EMERGENCY_MODE'] = 'false'
    # 禁用缓存预热器
    os.environ['CACHE_WARMER_ENABLED'] = 'false'
    
    # 设置线程数
    import threading
    logger.info(f"启动时活跃线程数: {threading.active_count()}")
    
    # 启动 Flask
    # 在生产环境中禁用debug模式，避免进程重启导致的问题
    debug_mode = False if is_production else True
    # 确保使用环境变量中的PORT，这对于Railway平台至关重要
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"应用将在端口 {port} 上启动")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)