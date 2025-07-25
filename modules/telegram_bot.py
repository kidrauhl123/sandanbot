import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
)
from modules.constants import BOT_TOKEN, STATUS, DATABASE_URL
from modules.database import (
    execute_query, get_active_seller_ids, update_seller_last_active, update_seller_info, get_all_sellers, get_seller_info
)

logger = logging.getLogger(__name__)

# 判断是否为卖家
def is_seller(user_id):
    return str(user_id) in [str(i) for i in get_active_seller_ids()]

# /seller 命令：显示卖家自己的订单
def get_seller_orders(user_id):
    orders = execute_query(
        "SELECT id, account, status, created_at FROM orders WHERE accepted_by = %s ORDER BY id DESC LIMIT 10",
        (str(user_id),), fetch=True
    )
    return orders

async def on_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_seller(user_id):
        await update.message.reply_text("你不是卖家，无权使用此命令。")
        return
    update_seller_info(str(user_id), update.effective_user.username, update.effective_user.first_name)
    update_seller_last_active(user_id)
    orders = get_seller_orders(user_id)
    if not orders:
        await update.message.reply_text("你当前没有接单。")
        return
    msg = "你的接单：\n"
    for o in orders:
        msg += f"订单ID: {o[0]}, 账号: {o[1]}, 状态: {o[2]}, 时间: {o[3]}\n"
    await update.message.reply_text(msg)

# /active 命令：切换卖家激活状态
async def on_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_seller(user_id):
        await update.message.reply_text("你不是卖家，无权使用此命令。")
        return
    # 切换激活状态
    execute_query("UPDATE sellers SET is_active = NOT is_active WHERE telegram_id = %s", (str(user_id),))
    update_seller_last_active(user_id)
    await update.message.reply_text("已切换你的接单激活状态。")

# 新订单通知（由web端调用，推送图片+备注给卖家）
async def send_new_order_notification(bot, seller_id, order_id, account, remark, qr_code_path=None):
    keyboard = [[
        InlineKeyboardButton("✅ 接单", callback_data=f"accept_{order_id}"),
        InlineKeyboardButton("❌ 失败", callback_data=f"fail_{order_id}"),
        InlineKeyboardButton("✔️ 完成", callback_data=f"done_{order_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"🆕 新订单通知\n📋 订单ID: {order_id}\n👤 账号: {account}\n📝 备注: {remark or '无'}"
    
    try:
        if qr_code_path and qr_code_path.strip():
            # 构建完整的文件路径
            import os
            full_path = os.path.join('static', qr_code_path)
            if os.path.exists(full_path):
                with open(full_path, 'rb') as photo_file:
                    await bot.send_photo(chat_id=seller_id, photo=photo_file, caption=caption, reply_markup=reply_markup)
            else:
                # 如果文件不存在，发送文本通知
                await bot.send_message(chat_id=seller_id, text=f"{caption}\n\n⚠️ 二维码文件未找到", reply_markup=reply_markup)
        else:
            # 没有二维码，只发送文本通知
            await bot.send_message(chat_id=seller_id, text=caption, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"发送Telegram通知失败: {str(e)}")
        # 发送备用文本通知
        try:
            await bot.send_message(chat_id=seller_id, text=f"{caption}\n\n⚠️ 图片发送失败", reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"发送备用Telegram通知也失败: {str(e2)}")

# 群发新订单通知给所有活跃卖家
async def notify_all_sellers(order_id, account, remark, qr_code_path=None):
    """向所有活跃卖家发送新订单通知"""
    try:
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        
        # 获取所有活跃卖家
        active_sellers = execute_query(
            "SELECT telegram_id FROM sellers WHERE is_active = true",
            fetch=True
        )
        
        if not active_sellers:
            logger.warning("没有活跃的卖家，无法发送订单通知")
            return
        
        logger.info(f"向 {len(active_sellers)} 个活跃卖家发送新订单通知，订单ID: {order_id}")
        
        for seller in active_sellers:
            seller_id = seller[0]
            try:
                await send_new_order_notification(bot, seller_id, order_id, account, remark, qr_code_path)
                logger.info(f"已向卖家 {seller_id} 发送订单通知")
            except Exception as e:
                logger.error(f"向卖家 {seller_id} 发送通知失败: {str(e)}")
                
    except Exception as e:
        logger.error(f"群发订单通知失败: {str(e)}")

# 同步版本的通知函数（用于在非异步环境中调用）
def notify_sellers_sync(order_id, account, remark, qr_code_path=None):
    """同步方式通知卖家（在新线程中运行异步函数）"""
    import threading
    import asyncio
    
    def run_async():
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(notify_all_sellers(order_id, account, remark, qr_code_path))
            loop.close()
        except Exception as e:
            logger.error(f"同步通知卖家失败: {str(e)}")
    
    # 在新线程中运行异步函数
    thread = threading.Thread(target=run_async)
    thread.daemon = True
    thread.start()

# 回调按钮处理：接单、完成、失败
async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    if not is_seller(user_id):
        await query.answer("无权操作", show_alert=True)
        return
    if data.startswith("accept_"):
        oid = int(data.split("_")[1])
        execute_query("UPDATE orders SET status=%s, accepted_by=%s, accepted_at=%s WHERE id=%s AND status=%s", (STATUS['ACCEPTED'], str(user_id), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), oid, STATUS['SUBMITTED']))
        await query.answer("已接单", show_alert=True)
    elif data.startswith("done_"):
        oid = int(data.split("_")[1])
        execute_query("UPDATE orders SET status=%s, completed_at=%s WHERE id=%s", (STATUS['COMPLETED'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), oid))
        await query.answer("已完成", show_alert=True)
    elif data.startswith("fail_"):
        oid = int(data.split("_")[1])
        execute_query("UPDATE orders SET status=%s WHERE id=%s", (STATUS['FAILED'], oid))
        await query.answer("已标记为失败", show_alert=True)

# 主循环
async def bot_main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("seller", on_seller))
    app.add_handler(CommandHandler("active", on_active))
    app.add_handler(CallbackQueryHandler(on_callback_query))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    while True:
        await asyncio.sleep(3600)

def process_telegram_update(update_data):
    """处理Telegram更新（用于webhook）"""
    try:
        # 这里可以添加webhook处理逻辑
        # 目前简化处理，只记录日志
        logger.info(f"处理Telegram更新: {update_data}")
    except Exception as e:
        logger.error(f"处理Telegram更新失败: {str(e)}")

def run_bot():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_main())