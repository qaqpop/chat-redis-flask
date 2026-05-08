"""
hik talk配置
"""

# Redis 连接配置
REDIS_CONFIG = {
    "host": "10.187.54.129",
    "port": 6379,
    "db": 0,
    "password": None,
    "decode_responses": True
}

# 服务器配置
SERVER_CONFIG = {
    "host": "0.0.0.0",
    "port": 6380
}

# List 保留的最新消息数量
RECENT_MESSAGES_LIMIT = 500

# 消息过期时间（秒），默认7天
MESSAGE_TTL = 7 * 24 * 3600

# 用户心跳超时时间（秒）
HEARTBEAT_TIMEOUT = 60
