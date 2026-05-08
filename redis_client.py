"""
Redis 连接管理模块
"""
import redis
from config import REDIS_CONFIG


class RedisManager:
    """Redis 连接管理器"""
    
    _instance = None
    _pool = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._pool = redis.ConnectionPool(
                host=REDIS_CONFIG["host"],
                port=REDIS_CONFIG["port"],
                db=REDIS_CONFIG["db"],
                password=REDIS_CONFIG["password"],
                decode_responses=REDIS_CONFIG["decode_responses"],
                max_connections=50
            )
        return cls._instance
    
    def get_client(self):
        """获取 Redis 客户端"""
        return redis.Redis(connection_pool=self._pool)
    
    def health_check(self):
        """检查 Redis 连接状态"""
        try:
            client = self.get_client()
            return client.ping()
        except redis.ConnectionError as e:
            print(f"Redis 连接失败: {e}")
            return False


# 全局单例
redis_manager = RedisManager()


def get_redis_client():
    """获取 Redis 客户端的便捷函数"""
    return redis_manager.get_client()
