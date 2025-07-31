#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
缓存预热脚本
定期提前加载需要的数据，以减轻首次访问的负担
"""

import time
import threading
import logging
import requests
import random
import os
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('cache_warmer')

# 全局配置
BASE_URL = os.getenv('APP_URL', 'http://localhost:5000')  # 应用URL，修改为localhost
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', 'admin_secret_token')  # 管理员令牌，用于不需要登录的API调用
WARM_INTERVAL = int(os.getenv('WARM_INTERVAL', 300))  # 预热间隔（秒），增加到5分钟
ENABLED = os.getenv('CACHE_WARMER_ENABLED', 'False').lower() == 'true'  # 默认禁用

# 预热会话
session = requests.Session()


def warm_orders_cache():
    """预热订单缓存"""
    try:
        logger.info("正在预热订单缓存...")
        
        # 尝试使用不同的参数预热订单API
        endpoints = [
            "/orders/recent?limit=5&lightweight=true",
            "/orders/recent?page=1&per_page=5&lightweight=true",
        ]
        
        for endpoint in endpoints:
            url = f"{BASE_URL}{endpoint}"
            # 添加必要的请求头
            headers = {
                'X-Cache-Warmer': 'true',
                'X-Admin-Token': ADMIN_TOKEN,
                'User-Agent': 'Cache-Warmer/1.0'
            }
                
            start_time = time.time()
            try:
                response = session.get(url, headers=headers, timeout=5)  # 减少超时时间
                elapsed_time = time.time() - start_time
                
                if response.status_code == 200:
                    logger.info(f"预热成功: {url} - 耗时: {elapsed_time:.2f}秒")
                else:
                    logger.warning(f"预热失败: {url} - 状态码: {response.status_code}")
            except requests.exceptions.ConnectionError:
                logger.error(f"连接失败: {url} - 服务器可能未启动")
                return  # 如果连接失败，直接返回，不尝试其他端点
            except requests.exceptions.Timeout:
                logger.error(f"请求超时: {url}")
                
    except Exception as e:
        logger.error(f"预热订单缓存出错: {str(e)}", exc_info=True)


def warm_static_resources():
    """预热静态资源"""
    try:
        logger.info("正在预热静态资源...")
        
        resources = [
            "/static/css/main.css",
            "/static/js/main.js",
            "/static/js/vendors.js"
        ]
        
        for resource in resources:
            url = f"{BASE_URL}{resource}"
            try:
                start_time = time.time()
                response = session.get(url, timeout=5)
                elapsed_time = time.time() - start_time
                
                if response.status_code == 200:
                    logger.info(f"静态资源预热成功: {url} - 耗时: {elapsed_time:.2f}秒")
                else:
                    logger.warning(f"静态资源预热失败: {url} - 状态码: {response.status_code}")
            except Exception as e:
                logger.error(f"预热静态资源失败: {url} - {str(e)}")
                
    except Exception as e:
        logger.error(f"预热静态资源出错: {str(e)}", exc_info=True)


def warm_cache_job():
    """预热缓存任务"""
    while ENABLED:
        try:
            # 随机延迟0-5秒，避免并发
            time.sleep(random.uniform(0, 5))
            
            # 记录开始时间
            start_time = time.time()
            logger.info(f"开始预热缓存 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 执行预热任务
            warm_orders_cache()
            warm_static_resources()
            
            # 计算总耗时
            total_time = time.time() - start_time
            logger.info(f"缓存预热完成 - 总耗时: {total_time:.2f}秒")
            
            # 等待下一次预热
            time.sleep(WARM_INTERVAL - (total_time % WARM_INTERVAL))
            
        except Exception as e:
            logger.error(f"缓存预热任务出错: {str(e)}", exc_info=True)
            time.sleep(30)  # 出错后等待30秒再重试


def start_cache_warmer():
    """启动缓存预热器"""
    if not ENABLED:
        logger.info("缓存预热器未启用")
        return
        
    logger.info(f"启动缓存预热器 - 目标: {BASE_URL}, 间隔: {WARM_INTERVAL}秒")
    
    # 创建一个守护线程运行预热任务
    warmer_thread = threading.Thread(target=warm_cache_job, daemon=True)
    warmer_thread.start()
    
    return warmer_thread


# 如果直接运行此脚本，则启动预热器
if __name__ == "__main__":
    thread = start_cache_warmer()
    try:
        # 保持主线程运行
        while thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("接收到中断信号，缓存预热器退出") 