# 破天充值系统 - 精简版

一个基于Flask和Telegram Bot的充值订单管理系统，专注于核心功能。

## 核心功能

- **买家功能**：上传二维码图片，创建充值订单
- **卖家功能**：接收订单通知，接单、完成、标记失败
- **订单管理**：订单状态跟踪（已提交、已接单、已完成、失败）
- **后台管理**：管理员查看和管理订单、卖家

## 技术栈

- **后端**：Flask (Python)
- **数据库**：PostgreSQL
- **机器人**：python-telegram-bot
- **前端**：HTML + CSS + JavaScript

## 环境变量

```bash
BOT_TOKEN=your-telegram-bot-token
DATABASE_URL=postgresql://user:password@host:port/database
FLASK_SECRET=your-secret-key
```

## 安装和运行

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 设置环境变量

3. 运行应用：
```bash
python app.py
```

## API接口

### 用户接口
- `POST /` - 创建订单（上传图片）
- `GET /` - 获取最近订单
- `POST /orders/confirm/<id>` - 确认订单完成

### 管理员接口
- `GET /admin/api/orders` - 获取所有订单
- `GET /admin/api/sellers` - 获取所有卖家
- `POST /admin/api/sellers` - 添加卖家
- `DELETE /admin/api/sellers/<id>` - 删除卖家

## Telegram Bot命令

- `/seller` - 卖家查看自己的订单
- `/active` - 切换卖家激活状态

## 文件结构

```
├── app.py              # 主应用文件
├── modules/
│   ├── constants.py    # 常量定义
│   ├── database.py     # 数据库操作
│   ├── telegram_bot.py # Telegram机器人
│   └── web_routes.py   # Web路由
├── templates/          # HTML模板
├── static/            # 静态文件
└── requirements.txt   # Python依赖
``` 