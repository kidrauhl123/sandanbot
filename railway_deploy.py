#!/usr/bin/env python3
"""
Railway部署脚本
在Railway环境中运行数据库迁移和启动应用
"""

import os
import logging
import sys

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_environment():
    """检查必要的环境变量"""
    required_vars = ['DATABASE_URL', 'BOT_TOKEN']
    missing_vars = []
    
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"缺少环境变量: {', '.join(missing_vars)}")
        return False
    
    logger.info("环境变量检查通过")
    return True

def run_migration():
    """运行数据库迁移"""
    try:
        logger.info("开始运行数据库迁移...")
        from migrate_db import migrate_database
        success = migrate_database()
        if success:
            logger.info("数据库迁移完成")
            return True
        else:
            logger.error("数据库迁移失败")
            return False
    except Exception as e:
        logger.error(f"数据库迁移异常: {str(e)}")
        return False

def start_application():
    """启动Flask应用"""
    try:
        logger.info("启动Flask应用...")
        from app import app
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"启动应用失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    logger.info("=== Railway 部署开始 ===")
    
    # 检查环境变量
    if not check_environment():
        sys.exit(1)
    
    # 运行数据库迁移
    if not run_migration():
        logger.warning("数据库迁移失败，但继续启动应用...")
    
    # 启动应用
    start_application() 