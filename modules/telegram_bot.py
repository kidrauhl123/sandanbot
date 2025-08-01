import asyncio
import threading
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import time
import os
from functools import wraps
import pytz
import sys
import functools
import sqlite3
import traceback
import psycopg2
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters
)

from modules.constants import (
    BOT_TOKEN, STATUS, PLAN_LABELS_EN,
    STATUS_TEXT_ZH, TG_PRICES, WEB_PRICES, SELLER_CHAT_IDS, DATABASE_URL
)

# 全局响应存储 - 供web端和TG端共享
global_seller_responses = {}
from modules.database import (
    get_order_details, execute_query, 
    get_unnotified_orders, get_active_seller_ids,
    update_seller_desired_orders, update_seller_last_active, get_active_sellers
)

# 设置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 中国时区
CN_TIMEZONE = pytz.timezone('Asia/Shanghai')

# 获取数据库连接
def get_db_connection():
    """获取数据库连接，根据环境变量决定使用SQLite或PostgreSQL"""
    
    try:
        if DATABASE_URL.startswith('postgres'):
            # PostgreSQL连接
            url = urlparse(DATABASE_URL)
            dbname = url.path[1:]
            user = url.username
            password = url.password
            host = url.hostname
            port = url.port
            
            logger.info(f"连接PostgreSQL数据库: {host}:{port}/{dbname}")
            
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port
            )
            return conn
        else:
            # SQLite连接
            # 使用绝对路径访问数据库
            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(current_dir, "orders.db")
            logger.info(f"连接SQLite数据库: {db_path}")
            print(f"DEBUG: 连接SQLite数据库: {db_path}")
            
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row  # 使查询结果可以通过列名访问
            return conn
    except Exception as e:
        logger.error(f"获取数据库连接时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 获取数据库连接时出错: {str(e)}")

# 错误处理装饰器
def callback_error_handler(func):
    """装饰器：捕获并处理回调函数中的异常"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception as e:
            user_id = None
            try:
                if update.effective_user:
                    user_id = update.effective_user.id
            except:
                pass
            
            error_msg = f"回调处理错误 [{func.__name__}] "
            if user_id:
                error_msg += f"用户ID: {user_id} "
            error_msg += f"错误: {str(e)}"
            
            logger.error(error_msg, exc_info=True)
            print(f"ERROR: {error_msg}")
            
            # 尝试通知用户
            try:
                if update.callback_query:
                    await update.callback_query.answer("Operation failed, please try again later", show_alert=True)
            except Exception as notify_err:
                logger.error(f"无法通知用户错误: {str(notify_err)}")
                print(f"ERROR: 无法通知用户错误: {str(notify_err)}")
            
            return None
    return wrapper

# 获取中国时间的函数
def get_china_time():
    """获取当前中国时间（UTC+8）"""
    # 强制使用中国时区，不受系统时区影响
    now = datetime.now()
    china_tz = pytz.timezone('Asia/Shanghai')
    china_now = china_tz.localize(now.replace(tzinfo=None))
    return china_now.strftime("%Y-%m-%d %H:%M:%S")

# ===== 全局变量 =====
bot_application = None
BOT_LOOP = None

# 跟踪等待额外反馈的订单
feedback_waiting = {}

# 用户信息缓存
user_info_cache = {}

# 全局变量
notification_queue = None  # 将在run_bot函数中初始化

# ===== TG 辅助函数 =====
def is_seller(chat_id):
    """检查用户是否为已授权的卖家"""
    # 只从数据库中获取卖家信息，因为环境变量中的卖家已经同步到数据库
    return chat_id in get_active_seller_ids()

# 添加处理 Telegram webhook 更新的函数
async def process_telegram_update_async(update_data, notification_queue):
    """异步处理来自Telegram webhook的更新"""
    global bot_application
    
    try:
        if not bot_application:
            logger.error("机器人应用未初始化，无法处理webhook更新")
            print("ERROR: 机器人应用未初始化，无法处理webhook更新")
            return
        
        # 将JSON数据转换为Update对象
        update = Update.de_json(data=update_data, bot=bot_application.bot)
        
        if not update:
            logger.error("无法将webhook数据转换为Update对象")
            print("ERROR: 无法将webhook数据转换为Update对象")
            return
        
        # 处理更新
        logger.info(f"正在处理webhook更新: {update.update_id}")
        print(f"DEBUG: 正在处理webhook更新: {update.update_id}")
        
        # 将更新分派给应用程序处理
        await bot_application.process_update(update)
        
        logger.info(f"webhook更新 {update.update_id} 处理完成")
        print(f"DEBUG: webhook更新 {update.update_id} 处理完成")
    
    except Exception as e:
        logger.error(f"处理webhook更新时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 处理webhook更新时出错: {str(e)}")

def process_telegram_update(update_data, notification_queue):
    """处理来自Telegram webhook的更新（同步包装器）"""
    global BOT_LOOP
    
    try:
        if not BOT_LOOP:
            logger.error("机器人事件循环未初始化，无法处理webhook更新")
            print("ERROR: 机器人事件循环未初始化，无法处理webhook更新")
            return
        
        # 在机器人的事件循环中运行异步处理函数
        asyncio.run_coroutine_threadsafe(
            process_telegram_update_async(update_data, notification_queue),
            BOT_LOOP
        )
        
        logger.info("已将webhook更新提交到机器人事件循环处理")
        print("DEBUG: 已将webhook更新提交到机器人事件循环处理")
    
    except Exception as e:
        logger.error(f"提交webhook更新到事件循环时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 提交webhook更新到事件循环时出错: {str(e)}")

async def get_user_info(user_id):
    """获取Telegram用户信息并缓存"""
    global bot_application, user_info_cache
    
    if not bot_application:
        return {"id": user_id, "username": str(user_id), "first_name": str(user_id), "last_name": ""}
    
    # 检查缓存
    if user_id in user_info_cache:
        return user_info_cache[user_id]
    
    try:
        user = await bot_application.bot.get_chat(user_id)
        user_info = {
            "id": user_id,
            "username": user.username or str(user_id),
            "first_name": user.first_name or str(user_id),
            "last_name": user.last_name or ""
        }
        user_info_cache[user_id] = user_info
        return user_info
    except Exception as e:
        logger.error(f"Failed to get user info for {user_id}: {e}")
        default_info = {"id": user_id, "username": str(user_id), "first_name": str(user_id), "last_name": ""}
        user_info_cache[user_id] = default_info
        return default_info

# ===== TG 命令处理 =====
processing_accepts = set()
processing_accepts_time = {}  # 记录每个接单请求的开始时间

# 清理超时的处理中请求
async def cleanup_processing_accepts():
    """定期清理超时的处理中请求"""
    global processing_accepts, processing_accepts_time
    current_time = time.time()
    timeout_keys = []
    
    try:
        # 检查所有处理中的请求
        for key, start_time in list(processing_accepts_time.items()):
            # 如果请求处理时间超过30秒，认为超时
            if current_time - start_time > 30:
                timeout_keys.append(key)
        
        # 从集合中移除超时的请求
        for key in timeout_keys:
            if key in processing_accepts:
                processing_accepts.remove(key)
                logger.info(f"已清理超时的接单请求: {key}")
            if key in processing_accepts_time:
                del processing_accepts_time[key]
                
        # 检查是否有不一致的数据（在processing_accepts中但不在processing_accepts_time中）
        for key in list(processing_accepts):
            if key not in processing_accepts_time:
                processing_accepts.remove(key)
                logger.warning(f"清理了不一致的接单请求数据: {key}")
        
        # 日志记录当前处理中的请求数量
        if processing_accepts:
            logger.debug(f"当前有 {len(processing_accepts)} 个处理中的接单请求")
    except Exception as e:
        logger.error(f"清理超时的接单请求时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 清理超时的接单请求时出错: {str(e)}")

async def on_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """测试命令处理函数"""
    user_id = update.effective_user.id
    
    if not is_seller(user_id):
        await update.message.reply_text("⚠️ You do not have permission to use this command.")
        return
    
    await update.message.reply_text(
        "✅ Bot is running normally!\n\n"
        f"• Current Time: {get_china_time()}\n"
        f"• Your User ID: {user_id}\n"
        "• Bot Status: Online\n\n"
        "For help, use the /start command to see available functions."
    )
    logger.info(f"用户 {user_id} 执行了测试命令")

async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始命令处理 - 同时用于加入分流"""
    user_id = update.effective_user.id
    
    if is_seller(user_id):
        # 检查当前分流状态
        current_status = execute_query(
            "SELECT is_active FROM sellers WHERE telegram_id = %s", 
            (str(user_id),), fetch=True
        )
        
        if current_status and len(current_status) > 0:
            is_currently_active = current_status[0][0]
            
            # 如果当前是暂停状态，则激活分流
            if not is_currently_active:
                execute_query("UPDATE sellers SET is_active = TRUE WHERE telegram_id = %s", (str(user_id),))
                await update.message.reply_text(
                    "✅ *Successfully Joined Order Distribution!* ✅\n\n"
                    "You are now receiving new orders.\n\n"
                    "Commands available:\n"
                    "• `/seller` - View available orders and your active orders\n"
                    "• `/stop` - Pause order distribution\n\n"
                    "Need assistance? Feel free to contact the administrator.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "🌟 *Welcome to the Premium Recharge System!* 🌟\n\n"
                    "You are already active and receiving orders.\n\n"
                    "Commands available:\n"
                    "• `/seller` - View available orders and your active orders\n"
                    "• `/stop` - Pause order distribution\n\n"
                    "Need assistance? Feel free to contact the administrator.",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "❌ *Seller Not Found* ❌\n\n"
                "Please contact the administrator.",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text(
            "⚠️ *Access Restricted* ⚠️\n\n"
            "This bot is exclusively available to authorized sellers.\n"
            "For account inquiries, please contact the administrator.",
            parse_mode='Markdown'
        )

async def on_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """停止命令处理 - 用于暂停分流"""
    user_id = update.effective_user.id
    
    if is_seller(user_id):
        # 检查当前分流状态
        current_status = execute_query(
            "SELECT is_active FROM sellers WHERE telegram_id = %s", 
            (str(user_id),), fetch=True
        )
        
        if current_status and len(current_status) > 0:
            is_currently_active = current_status[0][0]
            
            # 如果当前是激活状态，则暂停分流
            if is_currently_active:
                execute_query("UPDATE sellers SET is_active = FALSE WHERE telegram_id = %s", (str(user_id),))
                await update.message.reply_text(
                    "⏸️ *Order Distribution Paused* ⏸️\n\n"
                    "You will no longer receive new orders.\n"
                    "Your existing accepted orders remain active.\n\n"
                    "Use `/start` to resume receiving new orders.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "⏸️ *Already Paused* ⏸️\n\n"
                    "You are already not receiving new orders.\n"
                    "Your existing accepted orders remain active.\n\n"
                    "Use `/start` to resume receiving new orders.",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "❌ *Seller Not Found* ❌\n\n"
                "Please contact the administrator.",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text(
            "⚠️ *Access Restricted* ⚠️\n\n"
            "This bot is exclusively available to authorized sellers.\n"
            "For account inquiries, please contact the administrator.",
            parse_mode='Markdown'
        )

async def on_seller_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /seller 命令，显示卖家信息、活动订单和可用订单"""
    user_id = update.effective_user.id
    if not is_seller(user_id):
        await update.message.reply_text("您无权使用此命令。")
        return
    
    # 获取卖家自己的活动订单
    active_orders = execute_query(
        "SELECT id, package, created_at FROM orders WHERE accepted_by = ? AND status = ?",
        (str(user_id), STATUS['ACCEPTED']),
        fetch=True
    )

    # 获取可用的新订单
    available_orders = execute_query(
        "SELECT id, package, created_at FROM orders WHERE status = ?",
        (STATUS['SUBMITTED'],),
                fetch=True
            )
            
    message = f"🌟 *卖家控制台* 🌟\n\n*你好, {update.effective_user.first_name}!*\n\n"

    if active_orders:
        message += "--- *您的活动订单* ---\n"
        for order in active_orders:
            message += f"  - `订单 #{order[0]}` ({order[1]}个月), 创建于 {order[2]}\n"
        message += "\n"
    else:
        message += "✅ 您当前没有活动订单。\n\n"

    if available_orders:
        message += "--- *可接新订单* ---\n"
        for order in available_orders:
            message += f"  - `订单 #{order[0]}` ({order[1]}个月), 创建于 {order[2]}\n"
    else:
        message += "📭 当前没有可接的新订单。\n"

    await update.message.reply_text(message, parse_mode='Markdown')

# ====== 恢复 /orders 命令处理 ======
async def on_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置期望接单数量的命令"""
    user_id = update.effective_user.id
    
    if not is_seller(user_id):
        await update.message.reply_text("您不是卖家，无法使用此命令")
        return
    
    # 检查参数
    if not context.args or len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(
            "请提供您期望的每小时接单数量，例如：\n/orders 5"
        )
        return
    
    desired_orders = int(context.args[0])
    desired_orders = max(0, min(desired_orders, 20))  # 0~20 范围
    
    update_seller_desired_orders(user_id, desired_orders)
    update_seller_last_active(user_id)
    
    await update.message.reply_text(
        f"✅ 您的期望接单数量已设置为: {desired_orders} 单/小时"
    )
    logger.info(f"卖家 {user_id} 设置期望接单数量为 {desired_orders}")

# ===== 主函数 =====
def run_bot(queue):
    """在单独的线程中运行机器人"""
    global BOT_LOOP
    global bot_application
    global notified_orders_lock
    global notified_orders
    global notification_queue
    
    # 初始化锁和集合
    notified_orders_lock = threading.Lock()
    notified_orders = set()
    globals()['notification_queue'] = queue  # 设置全局变量
    
    try:
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        BOT_LOOP = loop
        
        # 运行机器人
        loop.run_until_complete(bot_main(queue))
    except Exception as e:
        logger.critical(f"运行机器人时发生严重错误: {str(e)}", exc_info=True)
        print(f"CRITICAL: 运行机器人时发生严重错误: {str(e)}")

async def bot_main(queue):
    """机器人的主异步函数"""
    global bot_application
    
    logger.info("正在启动Telegram机器人...")
    print("DEBUG: 正在启动Telegram机器人...")
    
    try:
        # 初始化，增加连接池大小和超时设置
        bot_application = (
            ApplicationBuilder()
            .token(BOT_TOKEN)
            .connection_pool_size(16)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .pool_timeout(30.0)
            .build()
        )
        
        logger.info("Telegram机器人应用已构建")
        print("DEBUG: Telegram机器人应用已构建")
        print(f"DEBUG: 使用的BOT_TOKEN: {BOT_TOKEN[:5]}...{BOT_TOKEN[-5:]}")
        
        # 添加处理程序
        bot_application.add_handler(CommandHandler("start", on_start))
        bot_application.add_handler(CommandHandler("stop", on_stop))
        bot_application.add_handler(CommandHandler("seller", on_seller_command))
        bot_application.add_handler(CommandHandler("orders", on_orders))  # 添加新命令
        
        # 添加测试命令处理程序
        bot_application.add_handler(CommandHandler("test", on_test))
        bot_application.add_handler(CommandHandler("test_notify", on_test_notify))  # 添加测试通知命令
        print("DEBUG: 已添加测试命令处理程序")
        
        # 添加通用回调处理程序，处理所有回调查询
        recharge_handler = CallbackQueryHandler(on_callback_query)
        bot_application.add_handler(recharge_handler)
        print(f"DEBUG: 已添加通用回调处理程序: {recharge_handler}")
        
        # 添加文本消息处理程序
        bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
        print("DEBUG: 已添加文本消息处理程序")
        
        logger.info("已添加所有处理程序")
        print("DEBUG: 已添加所有处理程序")
        
        # 添加错误处理程序
        bot_application.add_error_handler(error_handler)

        # 初始化应用
        logger.info("初始化Telegram应用...")
        await bot_application.initialize()
        
        # 获取Railway应用URL
        railway_url = os.environ.get('RAILWAY_STATIC_URL')
        if not railway_url:
            railway_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
            if railway_url:
                railway_url = f"https://{railway_url}"
        
        # 设置Webhook，添加重试机制和错误处理
        if railway_url:
            webhook_url = f"{railway_url}/telegram-webhook"
            
            # 先检查当前webhook设置
            try:
                webhook_info = await bot_application.bot.get_webhook_info()
                current_url = webhook_info.url
                
                # 如果webhook已经正确设置，则跳过
                if current_url == webhook_url:
                    logger.info(f"Webhook已经设置为正确的URL: {webhook_url}，无需更改")
                    print(f"DEBUG: Webhook已经设置为正确的URL: {webhook_url}，无需更改")
                else:
                    # 设置新的webhook
                    logger.info(f"设置 Telegram webhook: {webhook_url}")
                    print(f"DEBUG: 设置 Telegram webhook: {webhook_url}")
                    
                    # 添加重试机制
                    max_retries = 3
                    retry_count = 0
                    retry_delay = 2  # 初始延迟2秒
                    
                    while retry_count < max_retries:
                        try:
                            await bot_application.bot.set_webhook(
                                url=webhook_url,
                                allowed_updates=Update.ALL_TYPES
                            )
                            logger.info("Webhook设置成功")
                            break  # 成功设置，跳出循环
                        except Exception as e:
                            retry_count += 1
                            if "Flood control" in str(e):
                                logger.warning(f"Webhook设置触发流量控制，正在等待重试 ({retry_count}/{max_retries}): {str(e)}")
                                print(f"WARNING: Webhook设置触发流量控制，正在等待重试 ({retry_count}/{max_retries})")
                                
                                # 指数退避策略
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # 每次失败后增加等待时间
                            elif retry_count < max_retries:
                                logger.error(f"Webhook设置失败，正在重试 ({retry_count}/{max_retries}): {str(e)}")
                                await asyncio.sleep(retry_delay)
                            else:
                                logger.critical(f"Webhook设置失败，已达到最大重试次数: {str(e)}")
                                print(f"CRITICAL: Webhook设置失败，已达到最大重试次数: {str(e)}")
            except Exception as e:
                logger.error(f"检查webhook信息时出错: {str(e)}")
                print(f"ERROR: 检查webhook信息时出错: {str(e)}")
        else:
            logger.warning("无法获取公开URL，未设置webhook。机器人可能无法接收更新。")

        # 启动后台任务
        logger.info("启动后台任务...")
        asyncio.create_task(periodic_order_check())
        asyncio.create_task(process_notification_queue(queue))
        
        logger.info("Telegram机器人主循环已启动，等待更新...")
        print("DEBUG: Telegram机器人主循环已启动，等待更新...")
        
        # 保持此协程运行以使后台任务可以执行
        while True:
            await asyncio.sleep(3600) # 每小时唤醒一次，但主要目的是保持运行

    except Exception as e:
        logger.critical(f"Telegram机器人主函数 `bot_main` 发生严重错误: {str(e)}", exc_info=True)
        print(f"CRITICAL: Telegram机器人主函数 `bot_main` 发生严重错误: {str(e)}")

# 添加错误处理函数
async def error_handler(update, context):
    """处理Telegram机器人的错误"""
    logger.error(f"Telegram机器人发生错误: {context.error}", exc_info=context.error)
    print(f"ERROR: Telegram机器人发生错误: {context.error}")
    
    # 尝试获取错误来源
    if update:
        if update.effective_message:
            logger.error(f"错误发生在消息: {update.effective_message.text}")
            print(f"ERROR: 错误发生在消息: {update.effective_message.text}")
        elif update.callback_query:
            logger.error(f"错误发生在回调查询: {update.callback_query.data}")
            print(f"ERROR: 错误发生在回调查询: {update.callback_query.data}")
    
    # 如果是回调查询错误，尝试回复用户
    try:
        if update and update.callback_query:
            await update.callback_query.answer("An error occurred. Please try again later.", show_alert=True)
    except Exception as e:
        logger.error(f"尝试回复错误通知失败: {str(e)}")
        print(f"ERROR: 尝试回复错误通知失败: {str(e)}")

async def periodic_order_check():
    """定期检查未通知的订单"""
    logger.info("启动定期订单检查任务")
    while True:
        try:
            logger.debug("执行定期订单检查...")
            await check_and_push_orders()
        except Exception as e:
            logger.error(f"定期订单检查出错: {str(e)}", exc_info=True)
        
        # 每30秒检查一次
        await asyncio.sleep(30)

async def process_notification_queue(queue):
    """处理来自Flask的通知队列"""
    loop = asyncio.get_running_loop()
    while True:
        try:
            # 在执行器中运行阻塞的 queue.get()，这样不会阻塞事件循环
            data = await loop.run_in_executor(None, queue.get)
            logger.info(f"从队列中获取到通知任务: {data.get('type')}, 数据: {data}")
            
            # 确保调用send_notification_from_queue并等待其完成
            await send_notification_from_queue(data)
            
            # 标记任务完成
            queue.task_done()
            logger.info(f"通知任务 {data.get('type')} 处理完成")
        except asyncio.CancelledError:
            logger.info("通知队列处理器被取消。")
            break
        except Exception as e:
            # 捕获并记录所有其他异常
            logger.error(f"处理通知队列任务时发生未知错误: {repr(e)}", exc_info=True)
            # 等待一会避免在持续出错时刷屏
            await asyncio.sleep(5)
    
async def send_notification_from_queue(data):
    logger.info(f"[通知流程] 进入send_notification_from_queue, data: {data}")
    try:
        logger.info(f"[通知流程] 开始处理通知: {data.get('type')}")
        print(f"[通知流程] DEBUG: 开始处理通知: {data.get('type')}")
        
        if data.get('type') == 'new_order':
            # 获取订单数据
            order_id = data.get('order_id')
            account = data.get('account')  # 这是二维码图片路径
            remark = data.get('remark', '')  # 获取备注信息
            preferred_seller = data.get('preferred_seller')
            logger.info(f"[通知流程] 订单ID: {order_id}, preferred_seller: {preferred_seller}")
            
            # 检查订单是否存在
            order = get_order_by_id(order_id)
            if not order:
                logger.error(f"通知失败，找不到订单: {order_id}")
                return
            
            # 获取活跃卖家列表
            active_sellers = get_active_sellers()
            logger.info(f"获取到活跃卖家列表: {active_sellers}")
            print(f"DEBUG: 获取到活跃卖家列表: {active_sellers}")
            
            if not active_sellers:
                logger.warning(f"没有活跃的卖家可以接收订单通知: {order_id}")
                print(f"WARNING: 没有活跃的卖家可以接收订单通知: {order_id}")
                return
                
            image_path = account # 路径现在是相对的
            
            # 尝试不同的路径格式
            image_paths_to_try = [
                image_path,  # 原始路径
                image_path.replace('/', '\\'),  # Windows 风格路径
                os.path.join(os.getcwd(), image_path),  # 绝对路径
                os.path.join(os.getcwd(), image_path.replace('/', '\\')),  # 绝对 Windows 路径
            ]
            
            logger.info(f"将尝试以下图片路径:")
            for idx, path in enumerate(image_paths_to_try):
                logger.info(f"  路径 {idx+1}: {path} (存在: {os.path.exists(path)})")
                print(f"DEBUG: 尝试路径 {idx+1}: {path} (存在: {os.path.exists(path)})")
                
            # 找到第一个存在的路径
            valid_path = None
            for path in image_paths_to_try:
                if os.path.exists(path):
                    valid_path = path
                    logger.info(f"找到有效的图片路径: {valid_path}")
                    print(f"DEBUG: 找到有效的图片路径: {valid_path}")
                    break
                    
            if valid_path:
                image_path = valid_path
            else:
                logger.error(f"所有尝试的图片路径都不存在")
                print(f"ERROR: 所有尝试的图片路径都不存在")
                
            logger.info(f"将发送图片: {image_path}")
            print(f"DEBUG: 将发送图片: {image_path}")
            
            # 检查图片是否存在
            if not os.path.exists(image_path):
                logger.error(f"图片文件不存在: {image_path}")
                print(f"ERROR: 图片文件不存在: {image_path}")
                # 尝试列出目录内容
                try:
                    dir_path = os.path.dirname(image_path)
                    if os.path.exists(dir_path):
                        files = os.listdir(dir_path)
                        logger.info(f"目录 {dir_path} 中的文件: {files}")
                        print(f"DEBUG: 目录 {dir_path} 中的文件: {files}")
                    else:
                        logger.error(f"目录不存在: {dir_path}")
                        print(f"ERROR: 目录不存在: {dir_path}")
                except Exception as e:
                    logger.error(f"列出目录内容时出错: {str(e)}")
                    print(f"ERROR: 列出目录内容时出错: {str(e)}")
                return
                
            # 发送消息给卖家（如果指定了特定卖家，则只发给他们）
            logger.info(f"[通知流程] preferred_seller: {preferred_seller}, type: {type(preferred_seller)}")
            logger.info(f"[通知流程] active_sellers: {active_sellers}")
            
            # 确定目标卖家
            target_sellers = []
            if preferred_seller:
                # 尝试查找指定的卖家
                for seller in active_sellers:
                    seller_id = str(seller.get('id', ''))
                    if seller_id == str(preferred_seller):
                        target_sellers = [seller]
                        logger.info(f"[通知流程] 找到指定的卖家: {seller}")
                        break
                
                if not target_sellers:
                    logger.warning(f"[通知流程] 指定的卖家不存在或不活跃: {preferred_seller}")
                    # 如果没有找到指定卖家，使用所有活跃卖家
                    target_sellers = active_sellers
            else:
                # 没有指定卖家，使用所有活跃卖家
                target_sellers = active_sellers
            
            logger.info(f"[通知流程] 最终目标卖家: {target_sellers}")
            
            # 为订单添加状态标记
            await mark_order_as_processing(order_id)
            
            # 发送通知给选中的卖家
            for seller in target_sellers:
                seller_id = seller.get('id', '')
                try:
                    logger.info(f"准备发送图片给卖家 {seller_id}: {image_path}")
                    print(f"DEBUG: 准备发送图片给卖家 {seller_id}: {image_path}")
                    # Adding caption and reply_markup definitions here
                    caption = f"*{remark}*" if remark else f"新订单 #{order_id}"
                    keyboard = [
                        [InlineKeyboardButton("✅ Complete", callback_data=f"done_{order_id}"),
                         InlineKeyboardButton("❓ Any Problem", callback_data=f"fail_{order_id}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    import asyncio
                    try:
                        await asyncio.wait_for(
                            bot_application.bot.send_photo(
                                chat_id=seller_id,
                                photo=open(image_path, 'rb'),
                                caption=caption,
                                parse_mode='Markdown',
                                reply_markup=reply_markup
                            ),
                            timeout=10  # 10秒超时
                        )
                        logger.info(f"已发送图片给卖家 {seller_id}")
                        print(f"DEBUG: 已发送图片给卖家 {seller_id}")
                        await auto_accept_order(order_id, seller_id)
                        
                        # 成功发送给一个卖家后，不再发送给其他卖家
                        break
                    except asyncio.TimeoutError:
                        logger.error(f"发送图片给卖家 {seller_id} 超时")
                        print(f"ERROR: 发送图片给卖家 {seller_id} 超时")
                    except Exception as e:
                        logger.error(f"向卖家 {seller_id} 发送订单通知时出错: {str(e)}", exc_info=True)
                        print(f"ERROR: 向卖家 {seller_id} 发送订单通知时出错: {str(e)}")
                except Exception as e:
                    logger.error(f"处理卖家 {seller_id} 通知流程时出错: {str(e)}", exc_info=True)
                    print(f"ERROR: 处理卖家 {seller_id} 通知流程时出错: {str(e)}")
            
            # 成功发送通知后，标记订单为已通知
            from modules.database import mark_order_notified
            if mark_order_notified(order_id):
                logger.info(f"订单 #{order_id} 已标记为已通知，避免重复发送")
        
        elif data.get('type') == 'activity_check':
            # 处理卖家活跃度检查通知
            seller_id = data.get('seller_id')
            logger.info(f"[活跃度检查] 开始处理卖家 {seller_id} 的活跃度检查")
            print(f"DEBUG: [活跃度检查] 开始处理卖家 {seller_id} 的活跃度检查")
            
            if not seller_id:
                logger.error("活跃度检查失败：未提供卖家ID")
                return
                
            try:
                # 创建活跃度检查消息
                message = (
                    "🔔 *在线检查* 🔔\n\n"
                    "系统正在检查您是否在线。\n"
                    "如果您收到此消息，说明您的账号连接正常。\n\n"
                    "当前时间: " + get_china_time()
                )
                
                # 发送消息
                if bot_application and bot_application.bot:
                    await bot_application.bot.send_message(
                        chat_id=seller_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    logger.info(f"已发送活跃度检查消息给卖家 {seller_id}")
                    print(f"DEBUG: 已发送活跃度检查消息给卖家 {seller_id}")
                    
                    # 更新卖家最后活跃时间
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    timestamp = get_china_time()
                    
                    if DATABASE_URL.startswith('postgres'):
                        cursor.execute(
                            "UPDATE sellers SET last_active_at = %s WHERE telegram_id = %s",
                            (timestamp, seller_id)
                        )
                    else:
                        cursor.execute(
                            "UPDATE sellers SET last_active_at = ? WHERE telegram_id = ?",
                            (timestamp, seller_id)
                        )
                    conn.commit()
                    conn.close()
                    logger.info(f"已更新卖家 {seller_id} 的最后活跃时间为 {timestamp}")
                else:
                    logger.error("机器人未初始化，无法发送活跃度检查消息")
            except Exception as e:
                logger.error(f"发送活跃度检查消息给卖家 {seller_id} 失败: {str(e)}", exc_info=True)
                print(f"ERROR: 发送活跃度检查消息给卖家 {seller_id} 失败: {str(e)}")
        
        else:
            logger.warning(f"未知的通知类型: {data.get('type')}")
            print(f"WARNING: 未知的通知类型: {data.get('type')}")
            
    except Exception as e:
        logger.error(f"处理通知时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 处理通知时出错: {str(e)}")

async def mark_order_as_processing(order_id):
    """标记订单为处理中状态"""
    try:
        # 更新订单状态为处理中
        execute_query(
            "UPDATE orders SET status=? WHERE id=? AND status=?",
            (STATUS['SUBMITTED'], order_id, STATUS['SUBMITTED'])
        )
        logger.info(f"已标记订单 #{order_id} 为处理中状态")
    except Exception as e:
        logger.error(f"标记订单 #{order_id} 状态时出错: {str(e)}")

async def auto_accept_order(order_id, seller_id):
    """自动接单处理"""
    try:
        # 获取卖家信息
        user_info = await get_user_info(seller_id)
        username = user_info.get('username', '')
        first_name = user_info.get('first_name', '')
        
        logger.info(f"开始为卖家 {seller_id}({username or first_name}) 自动接单 #{order_id}")
        
        # 检查订单当前状态
        order = get_order_by_id(order_id)
        if not order:
            logger.error(f"自动接单失败：找不到订单 #{order_id}")
            return False
            
        current_status = order.get('status')
        if current_status != STATUS['SUBMITTED']:
            logger.warning(f"自动接单失败：订单 #{order_id} 当前状态为 {current_status}，不是未接单状态")
            return False
            
        # 更新订单为已接受状态
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 使用数据库函数更新订单状态
        if DATABASE_URL.startswith('postgres'):
            result = execute_query(
                "UPDATE orders SET status=%s, accepted_by=%s, accepted_at=%s, accepted_by_username=%s, accepted_by_first_name=%s WHERE id=%s AND status=%s RETURNING id",
                (STATUS['ACCEPTED'], str(seller_id), timestamp, username, first_name, order_id, STATUS['SUBMITTED']),
                fetch=True
            )
            success = result and len(result) > 0
        else:
            # SQLite没有RETURNING，所以我们使用rowcount
            result = execute_query(
                "UPDATE orders SET status=?, accepted_by=?, accepted_at=?, accepted_by_username=?, accepted_by_first_name=? WHERE id=? AND status=?",
                (STATUS['ACCEPTED'], str(seller_id), timestamp, username, first_name, order_id, STATUS['SUBMITTED'])
            )
            # 注：execute_query需要返回rowcount才能判断是否成功
            success = True  # 简化处理
            
        if success:
            logger.info(f"卖家 {seller_id}({username or first_name}) 已自动接受订单 #{order_id}")
            return True
        else:
            logger.warning(f"卖家 {seller_id} 自动接单失败，可能订单已被其他卖家接走")
            return False
    except Exception as e:
        logger.error(f"自动接单过程中出错: {str(e)}", exc_info=True)
        return False
    
def run_bot_in_thread():
    """在单独的线程中运行机器人"""
    # 这个函数现在可以被废弃或重构，因为启动逻辑已移至app.py
    logger.warning("run_bot_in_thread 已被调用，但可能已废弃。")
    pass

def restricted(func):
    """限制只有卖家才能访问的装饰器"""
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_seller(user_id):
            logger.warning(f"未经授权的访问: {user_id}")
            await update.message.reply_text("Sorry, you are not authorized to use this bot.")
    return wrapped 

def get_order_by_id(order_id):
    """根据ID获取订单信息"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error(f"获取订单 {order_id} 信息时无法获取数据库连接")
            print(f"ERROR: 获取订单 {order_id} 信息时无法获取数据库连接")
            return None
            
        cursor = conn.cursor()
        
        # 根据数据库类型执行不同的查询
        if DATABASE_URL.startswith('postgres'):
            # PostgreSQL使用%s作为占位符
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            order = cursor.fetchone()
            
            if order:
                # 将结果转换为字典
                columns = [desc[0] for desc in cursor.description]
                result = {columns[i]: order[i] for i in range(len(columns))}
                conn.close()
                return result
        else:
            # SQLite
            cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            order = cursor.fetchone()
            
            if order:
                # 将结果转换为字典
                columns = [column[0] for column in cursor.description]
                result = {columns[i]: order[i] for i in range(len(columns))}
                conn.close()
                return result
                
        conn.close()
        return None
    except Exception as e:
        logger.error(f"获取订单 {order_id} 信息时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 获取订单 {order_id} 信息时出错: {str(e)}")
        return None

def check_order_exists(order_id):
    """检查数据库中是否存在指定ID的订单"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error(f"检查订单 {order_id} 存在性时无法获取数据库连接")
            print(f"ERROR: 检查订单 {order_id} 存在性时无法获取数据库连接")
            return False
            
        cursor = conn.cursor()
        logger.info(f"正在检查订单ID={order_id}是否存在...")
        print(f"DEBUG: 正在检查订单ID={order_id}是否存在...")
        
        # 根据数据库类型执行不同的查询
        if DATABASE_URL.startswith('postgres'):
            # PostgreSQL使用%s作为占位符
            cursor.execute("SELECT COUNT(*) FROM orders WHERE id = %s", (order_id,))
        else:
            # SQLite
            cursor.execute("SELECT COUNT(*) FROM orders WHERE id = ?", (order_id,))
            
        count = cursor.fetchone()[0]
        
        # 增加更多查询记录debug问题
        if count == 0:
            logger.warning(f"订单 {order_id} 在数据库中不存在")
            print(f"WARNING: 订单 {order_id} 在数据库中不存在")
            
            # 检查是否有任何订单
            if DATABASE_URL.startswith('postgres'):
                cursor.execute("SELECT COUNT(*) FROM orders")
            else:
                cursor.execute("SELECT COUNT(*) FROM orders")
                
            total_count = cursor.fetchone()[0]
            logger.info(f"数据库中总共有 {total_count} 个订单")
            print(f"INFO: 数据库中总共有 {total_count} 个订单")
            
            # 列出最近的几个订单ID
            if DATABASE_URL.startswith('postgres'):
                cursor.execute("SELECT id FROM orders ORDER BY id DESC LIMIT 5")
            else:
                cursor.execute("SELECT id FROM orders ORDER BY id DESC LIMIT 5")
                
            recent_orders = cursor.fetchall()
            if recent_orders:
                recent_ids = [str(order[0]) for order in recent_orders]
                logger.info(f"最近的订单ID: {', '.join(recent_ids)}")
                print(f"INFO: 最近的订单ID: {', '.join(recent_ids)}")
        else:
            logger.info(f"订单 {order_id} 存在于数据库中")
            print(f"DEBUG: 订单 {order_id} 存在于数据库中")
            
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"检查订单 {order_id} 是否存在时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 检查订单 {order_id} 是否存在时出错: {str(e)}")
        return False

def update_order_status(order_id, status, handler_id=None):
    """更新订单状态"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error(f"更新订单 {order_id} 状态时无法获取数据库连接")
            return False
            
        cursor = conn.cursor()
        timestamp = get_china_time()
        
        # 根据数据库类型执行不同的查询
        if DATABASE_URL.startswith('postgres'):
            if status == STATUS['COMPLETED']:
                cursor.execute(
                    "UPDATE orders SET status = %s, completed_at = %s WHERE id = %s",
                    (status, timestamp, order_id)
                )
            elif status == STATUS['FAILED']:
                cursor.execute(
                    "UPDATE orders SET status = %s, completed_at = %s WHERE id = %s",
                    (status, timestamp, order_id)
                )
            else:
                cursor.execute(
                    "UPDATE orders SET status = %s, accepted_by = %s, accepted_at = %s WHERE id = %s",
                    (status, handler_id, timestamp, order_id)
                )
        else:
            # SQLite
            if status == STATUS['COMPLETED']:
                cursor.execute(
                    "UPDATE orders SET status = ?, completed_at = ? WHERE id = ?",
                    (status, timestamp, order_id)
                )
            elif status == STATUS['FAILED']:
                cursor.execute(
                    "UPDATE orders SET status = ?, completed_at = ? WHERE id = ?",
                    (status, timestamp, order_id)
                )
            else:
                cursor.execute(
                    "UPDATE orders SET status = ?, accepted_by = ?, accepted_at = ? WHERE id = ?",
                    (status, handler_id, timestamp, order_id)
                )
        
        conn.commit()
        conn.close()
        
        logger.info(f"已更新订单 {order_id} 状态为 {status}")
        return True
    except Exception as e:
        logger.error(f"更新订单 {order_id} 状态时出错: {str(e)}", exc_info=True)
        return False
 
@callback_error_handler
async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    logger.info(f"收到回调查询: 用户={user_id}, 数据={data}")
    
    # 立即应答回调查询，避免超时
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"应答回调查询失败: {str(e)}")
    
    try:
        if data.startswith('done_'):
            # 处理完成订单
            order_id = int(data.split('_')[1])
            logger.info(f"卖家 {user_id} 完成订单 {order_id}")
            
            # 更新订单状态
            if update_order_status(order_id, STATUS['COMPLETED'], user_id):
                # 更新按钮状态
                keyboard = [[InlineKeyboardButton("✅ 已完成", callback_data="completed")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.edit_message_reply_markup(reply_markup=reply_markup)
                    logger.info(f"订单 {order_id} 按钮状态已更新")
                except Exception as e:
                    logger.warning(f"更新按钮状态失败: {str(e)}")
                    # 如果更新按钮失败，发送新消息
                    try:
                        await query.message.reply_text(f"✅ 订单 #{order_id} 已完成！")
                    except Exception as e2:
                        logger.error(f"发送完成消息也失败: {str(e2)}")
            else:
                try:
                    await query.message.reply_text(f"❌ 更新订单 #{order_id} 状态失败")
                except Exception as e:
                    logger.error(f"发送失败消息失败: {str(e)}")
                    
        elif data.startswith('fail_'):
            # 处理失败订单
            order_id = int(data.split('_')[1])
            logger.info(f"卖家 {user_id} 标记订单 {order_id} 失败")
            
            # 更新订单状态
            if update_order_status(order_id, STATUS['FAILED'], user_id):
                # 更新按钮状态
                keyboard = [[InlineKeyboardButton("❌ 已失败", callback_data="failed")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await query.edit_message_reply_markup(reply_markup=reply_markup)
                    logger.info(f"订单 {order_id} 按钮状态已更新为失败")
                except Exception as e:
                    logger.warning(f"更新按钮状态失败: {str(e)}")
                    # 如果更新按钮失败，发送新消息
                    try:
                        await query.message.reply_text(f"❌ 订单 #{order_id} 已标记为失败")
                    except Exception as e2:
                        logger.error(f"发送失败消息也失败: {str(e2)}")
            else:
                try:
                    await query.message.reply_text(f"❌ 更新订单 #{order_id} 状态失败")
                except Exception as e:
                    logger.error(f"发送失败消息失败: {str(e)}")
        
    except Exception as e:
        logger.error(f"处理回调查询时出错: {str(e)}", exc_info=True)
        try:
            await query.message.reply_text("处理请求时出错，请重试")
        except Exception as e2:
            logger.error(f"发送错误消息失败: {str(e2)}")

# ====== 自动修复：添加测试通知命令处理函数 ======
async def on_test_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """测试通知命令处理函数"""
    user_id = update.effective_user.id
    
    if not is_seller(user_id):
        await update.message.reply_text("⚠️ 您没有权限使用此命令。")
        return
        
    try:
        await update.message.reply_text("正在测试通知功能，将发送测试通知...")
        
        # 创建测试数据
        test_image_path = "static/uploads/test_notify.png"
        
        # 创建一个简单的测试图片
        try:
            from PIL import Image, ImageDraw, ImageFont
            import random
            
            # 创建一个白色背景图片
            img = Image.new('RGB', (300, 300), color=(255, 255, 255))
            d = ImageDraw.Draw(img)
            
            # 添加一些随机彩色矩形
            for i in range(10):
                x1 = random.randint(0, 250)
                y1 = random.randint(0, 250)
                x2 = x1 + random.randint(10, 50)
                y2 = y1 + random.randint(10, 50)
                color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                d.rectangle([x1, y1, x2, y2], fill=color)
            
            # 添加文本
            d.text((10, 10), f"测试通知 {time.time()}", fill=(0, 0, 0))
            
            # 确保目录存在
            os.makedirs(os.path.dirname(test_image_path), exist_ok=True)
            
            # 保存图片
            img.save(test_image_path)
            logger.info(f"已创建测试图片: {test_image_path}")
        except Exception as e:
            logger.error(f"创建测试图片失败: {str(e)}")
            test_image_path = None
        
        if test_image_path and os.path.exists(test_image_path):
            # 发送测试通知
            await send_order_notification_direct(999999, test_image_path, '这是一条测试通知', str(user_id))
            await update.message.reply_text("测试通知已发送，请检查是否收到")
        else:
            await update.message.reply_text("创建测试图片失败，无法发送测试通知")
    except Exception as e:
        logger.error(f"发送测试通知失败: {str(e)}", exc_info=True)
        await update.message.reply_text(f"发送测试通知失败: {str(e)}")

# ====== 自动修复：添加缺失的check_and_push_orders函数 ======
async def check_and_push_orders():
    """检查新订单并推送通知"""
    try:
        # 导入必要的函数
        from modules.database import get_unnotified_orders
        from app import get_notification_queue
        
        # 获取未通知的订单
        unnotified_orders = get_unnotified_orders()
        
        if unnotified_orders:
            logger.info(f"发现 {len(unnotified_orders)} 个未通知的订单")
            print(f"DEBUG: 发现 {len(unnotified_orders)} 个未通知的订单")
            
            # 处理每个未通知的订单
            for order in unnotified_orders:
                # 注意：order是一个元组，不是字典
                # 根据get_unnotified_orders的SQL查询，元素顺序为:
                # id, account, password, package, created_at, web_user_id, remark
                order_id = order[0]
                account = order[1]  # 图片路径
                remark = order[6] if len(order) > 6 else ""
                
                # 立即标记为已通知，避免重复处理
                from modules.database import mark_order_notified
                mark_order_notified(order_id)
                
                # 使用全局通知队列
                global notification_queue
                queue_to_use = get_notification_queue() or notification_queue
                
                if queue_to_use:
                    # 添加到通知队列
                    queue_to_use.put({
                        'type': 'new_order',
                        'order_id': order_id,
                        'account': account,
                        'remark': remark,
                        'preferred_seller': None  # 不指定特定卖家
                    })
                    logger.info(f"已将订单 #{order_id} 添加到通知队列")
                    print(f"DEBUG: 已将订单 #{order_id} 添加到通知队列")
                else:
                    logger.error("通知队列未初始化")
                    print("ERROR: 通知队列未初始化")
        else:
            logger.debug("没有发现未通知的订单")
    except Exception as e:
        logger.error(f"检查未通知订单时出错: {str(e)}", exc_info=True)
        print(f"ERROR: 检查未通知订单时出错: {str(e)}")

# ====== 添加文本消息处理函数 ======
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理普通文本消息"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # 记录接收到的消息
    logger.info(f"收到来自用户 {user_id} 的文本消息: {text}")
    print(f"DEBUG: 收到来自用户 {user_id} 的文本消息: {text}")
    
    # 如果是卖家，可以提供一些帮助信息
    if is_seller(user_id):
        # 只回复第一条消息，避免重复打扰
        if not hasattr(context.user_data, 'welcomed'):
            await update.message.reply_text(
                "👋 您好！如需使用机器人功能，请使用以下命令：\n"
                "/seller - 查看可接订单和活动订单\n"
                "/test_notify - 测试通知功能\n"
                "/test - 测试机器人状态"
            )
            context.user_data['welcomed'] = True

async def send_order_notification_direct(order_id, account, remark, preferred_seller):
    """直接发送订单通知给指定卖家，不使用队列"""
    logger.info(f"[直接通知] 开始处理订单 #{order_id} 的通知，目标卖家: {preferred_seller}")
    
    try:
        # 检查bot_application是否可用
        global bot_application
        if not bot_application or not bot_application.bot:
            logger.error(f"[直接通知] bot_application 未初始化")
            return False
        
        # 检查订单是否存在
        order = get_order_by_id(order_id)
        if not order:
            logger.error(f"[直接通知] 找不到订单: {order_id}")
            return False
        
        # 检查图片文件是否存在
        image_path = account
        if not os.path.isabs(image_path):
            # 如果是相对路径，转换为绝对路径
            image_path = os.path.join(os.getcwd(), account)
        
        if not os.path.exists(image_path):
            logger.error(f"[直接通知] 图片文件不存在: {image_path}")
            return False
        
        logger.info(f"[直接通知] 找到图片文件: {image_path}")
        
        # 准备消息内容
        caption = f"*{remark}*" if remark else f"新订单 #{order_id}"
        keyboard = [
            [InlineKeyboardButton("✅ Complete", callback_data=f"done_{order_id}"),
             InlineKeyboardButton("❓ Any Problem", callback_data=f"fail_{order_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 直接发送图片消息
        try:
            with open(image_path, 'rb') as photo_file:
                # 减少超时时间，避免阻塞
                photo_result = await asyncio.wait_for(
                    bot_application.bot.send_photo(
                        chat_id=int(preferred_seller),
                        photo=photo_file,
                        caption=caption,
                        parse_mode='Markdown',
                        reply_markup=reply_markup
                    ),
                    timeout=8  # 减少到8秒超时
                )
            
            logger.info(f"[直接通知] 成功发送图片给卖家 {preferred_seller}，消息ID: {photo_result.message_id}")
            
            # 自动接单
            success = await auto_accept_order(order_id, preferred_seller)
            if success:
                logger.info(f"[直接通知] 卖家 {preferred_seller} 自动接单成功")
            else:
                logger.warning(f"[直接通知] 卖家 {preferred_seller} 自动接单失败")
            
            return True
            
        except asyncio.TimeoutError:
            logger.error(f"[直接通知] 发送图片给卖家 {preferred_seller} 超时，尝试简化发送")
            # 超时后尝试发送简单文本消息
            try:
                await asyncio.wait_for(
                    bot_application.bot.send_message(
                        chat_id=int(preferred_seller),
                        text=f"新订单 #{order_id}\n图片: {image_path}\n备注: {remark or '无'}"
                    ),
                    timeout=5
                )
                logger.info(f"[直接通知] 发送简化文本消息成功")
                # 仍然尝试自动接单
                await auto_accept_order(order_id, preferred_seller)
                return True
            except Exception as e:
                logger.error(f"[直接通知] 发送简化消息也失败: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"[直接通知] 发送图片失败: {str(e)}", exc_info=True)
            return False
    
    except Exception as e:
        logger.error(f"[直接通知] 函数执行失败: {str(e)}", exc_info=True)
        return False