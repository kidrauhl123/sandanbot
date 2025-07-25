import os
from collections import defaultdict
import threading
import logging
import time

# 设置日志
logger = logging.getLogger(__name__)

# ✅ 写死变量（优先）
if not os.environ.get('BOT_TOKEN'):
    os.environ['BOT_TOKEN'] = '7952478409:AAHdi7_JOjpHu_WAM8mtBewe0m2GWLLmvEk'

BOT_TOKEN = os.environ["BOT_TOKEN"]

# ✅ 管理员默认凭证（优先从环境变量读取）
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', '755439')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '755439')

if ADMIN_USERNAME == '755439' or ADMIN_PASSWORD == '755439':
    logger.warning("正在使用默认的管理员凭证。为了安全，请设置 ADMIN_USERNAME 和 ADMIN_PASSWORD 环境变量。")

# 支持通过环境变量设置卖家ID
SELLER_CHAT_IDS = []
if os.environ.get('SELLER_CHAT_IDS'):
    try:
        # 格式: "123456789,987654321"
        seller_ids_str = os.environ.get('SELLER_CHAT_IDS', '')
        SELLER_CHAT_IDS = [int(x.strip()) for x in seller_ids_str.split(',') if x.strip()]
        logger.info(f"从环境变量加载卖家ID: {SELLER_CHAT_IDS}")
    except Exception as e:
        logger.error(f"解析SELLER_CHAT_IDS环境变量出错: {e}")

# 将环境变量中的卖家ID同步到数据库
def sync_env_sellers_to_db():
    """将环境变量中的卖家ID同步到数据库"""
    if not SELLER_CHAT_IDS:
        return
    
    # 导入放在函数内部，避免循环导入
    from modules.database import execute_query
    
    # 获取数据库中已存在的卖家ID
    try:
        db_seller_ids = execute_query("SELECT telegram_id FROM sellers", fetch=True)
        db_seller_ids = [row[0] for row in db_seller_ids] if db_seller_ids else []
        
        # 将环境变量中的卖家ID添加到数据库
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        for seller_id in SELLER_CHAT_IDS:
            if seller_id not in db_seller_ids:
                logger.info(f"将环境变量中的卖家ID {seller_id} 同步到数据库")
                execute_query(
                    "INSERT INTO sellers (telegram_id, username, first_name, nickname, is_active, added_at, added_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (seller_id, f"env_seller_{seller_id}", f"环境变量卖家 {seller_id}", f"卖家 {seller_id}", 1, timestamp, "环境变量")
                )
    except Exception as e:
        logger.error(f"同步环境变量卖家到数据库失败: {e}")

# ===== 价格系统 =====
# 网页端价格（美元USDT）
WEB_PRICES = {
    '1': 5,     # 1个月
    '2': 9,     # 2个月
    '3': 13,    # 3个月
    '6': 16,    # 6个月
    '12': 20    # 12个月
}
# Telegram端卖家薪资（美元）
TG_PRICES = {
    '1': 2.5,   # 1个月
    '2': 4.5,   # 2个月
    '3': 6.5,   # 3个月
    '6': 8,     # 6个月
    '12': 10    # 12个月
}

# 获取用户套餐价格
def get_user_package_price(user_id, package):
    """
    获取特定用户的套餐价格
    
    参数:
    - user_id: 用户ID
    - package: 套餐（如'1'，'2'等）
    
    返回:
    - 用户的套餐价格，如果没有定制价格则返回默认价格
    """
    # 如果没有用户ID，返回默认价格
    if not user_id:
        return WEB_PRICES.get(package, 0)
        
    # 避免循环导入
    from modules.database import get_user_custom_prices
    
    # 获取用户定制价格
    custom_prices = get_user_custom_prices(user_id)
    
    # 如果该套餐有定制价格，返回定制价格，否则返回默认价格
    return custom_prices.get(package, WEB_PRICES.get(package, 0))

# ===== 状态常量 =====
STATUS = {
    'SUBMITTED': 'submitted',
    'ACCEPTED': 'accepted',
    'COMPLETED': 'completed',
    'FAILED': 'failed',
    'CANCELLED': 'cancelled',
    'DISPUTING': 'disputing'
}
STATUS_TEXT_ZH = {
    'submitted': '已提交', 'accepted': '已接单', 'completed': '充值成功',
    'failed': '充值失败', 'cancelled': '已撤销', 'disputing': '正在质疑'
}
PLAN_OPTIONS = [('12', '一年个人会员')]
PLAN_LABELS_ZH = {v: l for v, l in PLAN_OPTIONS}
PLAN_LABELS_EN = {'12': '1 Year Premium'}

# 失败原因的中英文映射
REASON_TEXT_ZH = {
    'Wrong password': '密码错误',
    'Membership not expired': '会员未到期',
    'Other reason': '其他原因',
    'Other reason (details pending)': '其他原因',
    'Unknown reason': '未知原因'
}

# ===== 全局变量 =====
user_languages = defaultdict(lambda: 'en')
feedback_waiting = {}
notified_orders = set()
notified_orders_lock = threading.Lock()  # 在主应用中初始化

# 数据库连接URL（用于PostgreSQL判断，默认为SQLite）
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///orders.db')

# 用户信息缓存
user_info_cache = {} 