import os

# 机器人Token
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'your-bot-token')

# 数据库连接URL
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/sandanbot')

# 订单状态常量
STATUS = {
    'SUBMITTED': 'submitted',
    'ACCEPTED': 'accepted',
    'COMPLETED': 'completed',
    'FAILED': 'failed',
    'CANCELLED': 'cancelled',
    'DISPUTING': 'disputing'
}

STATUS_TEXT_ZH = {
    'submitted': '已提交',
    'accepted': '已接单',
    'completed': '充值成功',
    'failed': '充值失败',
    'cancelled': '已撤销',
    'disputing': '正在质疑'
} 