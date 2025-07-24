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
        "SELECT id, account, package, status, created_at FROM orders WHERE accepted_by = %s ORDER BY id DESC LIMIT 10",
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
        msg += f"订单ID: {o[0]}, 套餐: {o[2]}, 状态: {o[3]}, 时间: {o[4]}\n"
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
async def send_new_order_notification(bot, seller_id, order_id, account, remark):
    keyboard = [[
        InlineKeyboardButton("✅ 接单", callback_data=f"accept_{order_id}"),
        InlineKeyboardButton("❌ 失败", callback_data=f"fail_{order_id}"),
        InlineKeyboardButton("✔️ 完成", callback_data=f"done_{order_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"新订单\n订单ID: {order_id}\n备注: {remark}"
    with open(account, 'rb') as photo_file:
        await bot.send_photo(chat_id=seller_id, photo=photo_file, caption=caption, reply_markup=reply_markup)

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

def run_bot():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_main())