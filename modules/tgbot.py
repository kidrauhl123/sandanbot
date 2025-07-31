"""
Telegram机器人启动模块
这个模块提供了一个统一的接口来启动Telegram机器人
"""

import logging
from modules.telegram_bot import run_bot

logger = logging.getLogger(__name__)

def start_bot():
    """
    启动Telegram机器人的统一接口函数
    
    这个函数会：
    1. 创建一个通知队列
    2. 调用telegram_bot模块的run_bot函数
    3. 直接运行机器人（在调用线程中）
    """
    try:
        import queue
        
        # 创建通知队列
        notification_queue = queue.Queue()
        
        # 直接运行机器人
        run_bot(notification_queue)
        
        logger.info("Telegram机器人启动成功")
        
    except Exception as e:
        logger.error(f"启动Telegram机器人失败: {str(e)}", exc_info=True) 