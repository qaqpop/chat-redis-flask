"""
用户管理模块
使用 Redis 数据结构: Hash, Set, ZSet, String
"""
import time
from redis_client import get_redis_client


class UserManager:
    """用户管理器"""
    
    # Hash: 存储用户信息
    # Key: chat:user:{user_id}
    # Fields: username, avatar, register_time, last_login
    
    # Hash: 存储用户在线状态
    # Key: chat:online:user:{user_id}
    # Fields: user_id, username, room_id, login_time, last_heartbeat
    
    # Set: 全局在线用户
    # Key: chat:online:users
    
    # Set: 用户加入的房间
    # Key: chat:set:user:{user_id}:rooms
    
    # ZSet: 用户消息排行
    # Key: chat:zset:user:{user_id}:leaderboard
    
    # String: 消息计数器
    # Key: chat:config:user_msg_count:{user_id}
    
    @staticmethod
    def register_user(user_id, username, avatar=""):
        """
        注册用户
        使用: Hash(HSET), String(INCR)
        """
        r = get_redis_client()
        user_key = f"chat:user:{user_id}"
        
        # 检查用户是否已存在
        if r.exists(user_key):
            return {"success": False, "message": f"用户 {user_id} 已存在"}
        
        # 使用 Hash 存储用户信息（Redis 3.x 兼容）
        r.hset(user_key, "user_id", user_id)
        r.hset(user_key, "username", username)
        r.hset(user_key, "avatar", avatar)
        r.hset(user_key, "register_time", str(int(time.time())))
        r.hset(user_key, "last_login", str(int(time.time())))
        
        # 初始化消息计数器
        r.set(f"chat:config:user_msg_count:{user_id}", 0)
        
        return {
            "success": True,
            "user_id": user_id,
            "username": username,
            "message": "注册成功"
        }
    
    @staticmethod
    def login(user_id, username=""):
        """
        用户登录
        使用: Hash(HSET), Set(SADD)
        """
        r = get_redis_client()
        user_key = f"chat:user:{user_id}"
        
        # 检查用户是否存在
        if not r.exists(user_key):
            # 自动注册新用户
            UserManager.register_user(user_id, username)
        
        # 更新最后登录时间
        r.hset(user_key, "last_login", str(int(time.time())))
        
        # 更新在线状态 Hash（Redis 3.x 兼容）
        online_key = f"chat:online:user:{user_id}"
        r.hset(online_key, "user_id", user_id)
        r.hset(online_key, "username", username or r.hget(user_key, "username"))
        r.hset(online_key, "room_id", "")
        r.hset(online_key, "login_time", str(int(time.time())))
        r.hset(online_key, "last_heartbeat", str(int(time.time())))
        
        # 添加到全局在线用户 Set
        r.sadd("chat:online:users", user_id)
        
        return {
            "success": True,
            "message": f"{username or user_id} 登录成功"
        }
    
    @staticmethod
    def logout(user_id):
        """
        用户登出
        使用: Set(SREM), Hash(HDEL)
        """
        r = get_redis_client()
        
        # 从在线用户中移除
        r.srem("chat:online:users", user_id)
        
        # 获取用户当前所在房间，从房间成员中移除
        room_id = r.hget(f"chat:online:user:{user_id}", "room_id")
        if room_id:
            from room import RoomManager
            RoomManager.leave_room(room_id, user_id)
        
        # 删除在线状态
        r.delete(f"chat:online:user:{user_id}")
        
        return {"success": True, "message": f"用户 {user_id} 已登出"}
    
    @staticmethod
    def heartbeat(user_id):
        """
        用户心跳更新
        使用: Hash(HSET)
        """
        r = get_redis_client()
        r.hset(f"chat:online:user:{user_id}", "last_heartbeat", str(int(time.time())))
        return {"success": True}
    
    @staticmethod
    def get_online_users():
        """
        获取所有在线用户
        使用: Set(SMEMBERS), Hash(HGETALL)
        """
        r = get_redis_client()
        online_user_ids = r.smembers("chat:online:users")
        online_users = []
        
        for user_id in online_user_ids:
            user_info = r.hgetall(f"chat:online:user:{user_id}")
            if user_info:
                # 检查心跳是否超时
                last_heartbeat = int(user_info.get("last_heartbeat", 0))
                from config import HEARTBEAT_TIMEOUT
                if int(time.time()) - last_heartbeat > HEARTBEAT_TIMEOUT:
                    # 心跳超时，自动移除
                    UserManager.logout(user_id)
                else:
                    online_users.append(user_info)
        
        return online_users
    
    @staticmethod
    def is_online(user_id):
        """
        检查用户是否在线
        使用: Set(SISMEMBER)
        """
        r = get_redis_client()
        return r.sismember("chat:online:users", user_id)
    
    @staticmethod
    def get_user_info(user_id):
        """
        获取用户信息
        使用: Hash(HGETALL)
        """
        r = get_redis_client()
        user_key = f"chat:user:{user_id}"
        return r.hgetall(user_key)
    
    @staticmethod
    def update_user_info(user_id, **kwargs):
        """
        更新用户信息
        使用: Hash(HSET)
        """
        r = get_redis_client()
        user_key = f"chat:user:{user_id}"
        
        # 过滤掉不存在的字段
        valid_fields = ["username", "avatar"]
        update_data = {k: v for k, v in kwargs.items() if k in valid_fields and v}
        
        if update_data:
            r.hset(user_key, mapping=update_data)
            
            # 如果更新了用户名，同步更新在线状态
            if "username" in update_data:
                r.hset(f"chat:online:user:{user_id}", "username", update_data["username"])
            
            return {"success": True, "message": "用户信息更新成功"}
        
        return {"success": False, "message": "没有需要更新的字段"}
    
    @staticmethod
    def join_room(user_id, room_id):
        """
        记录用户加入的房间
        使用: Set(SADD)
        """
        r = get_redis_client()
        r.sadd(f"chat:set:user:{user_id}:rooms", room_id)
        return {"success": True}
    
    @staticmethod
    def get_user_rooms(user_id):
        """
        获取用户加入的所有房间
        使用: Set(SMEMBERS)
        """
        r = get_redis_client()
        return r.smembers(f"chat:set:user:{user_id}:rooms")
    
    @staticmethod
    def increment_msg_count(user_id):
        """
        增加用户消息计数
        使用: String(INCR)
        """
        r = get_redis_client()
        return r.incr(f"chat:config:user_msg_count:{user_id}")
    
    @staticmethod
    def get_msg_count(user_id):
        """
        获取用户消息总数
        使用: String(GET)
        """
        r = get_redis_client()
        count = r.get(f"chat:config:user_msg_count:{user_id}")
        return int(count) if count else 0
    
    @staticmethod
    def get_leaderboard(room_id, start=0, end=9):
        """
        获取房间消息排行榜
        使用: ZSet(ZREVRANGE)
        """
        r = get_redis_client()
        # 这里使用房间维度的排行榜
        leaderboard_key = f"chat:zset:room:{room_id}:leaderboard"
        return r.zrevrange(leaderboard_key, start, end, withscores=True)
    
    @staticmethod
    def get_user_activity(user_id):
        """
        获取用户活动记录
        使用: ZSet(ZRANGEBYSCORE)
        """
        r = get_redis_client()
        # 用户活动时间线
        activity_key = f"chat:zset:user:{user_id}:activity"
        return r.zrange(activity_key, 0, -1, withscores=True)
