"""
房间管理模块
使用 Redis 数据结构: Hash, Set, String, ZSet
"""
import time
from redis_client import get_redis_client


class RoomManager:
    """房间管理器"""
    
    # Hash: 存储房间信息
    # Key: chat:room:{room_id}
    # Fields: name, created_at, description, creator
    
    # Set: 存储房间成员
    # Key: chat:room:{room_id}:members
    
    # String: 房间计数器
    # Key: chat:config:room_counter
    
    # ZSet: 房间活跃度
    # Key: chat:zset:room:{room_id}:activity
    
    @staticmethod
    def _get_room_key(room_id):
        """获取房间 Hash 的 key"""
        return f"chat:room:{room_id}"
    
    @staticmethod
    def _get_members_key(room_id):
        """获取房间成员 Set 的 key"""
        return f"chat:room:{room_id}:members"
    
    @staticmethod
    def _get_activity_key(room_id):
        """获取房间活跃度 ZSet 的 key"""
        return f"chat:zset:room:{room_id}:activity"
    
    @staticmethod
    def create_room(room_id, name, description="", creator=""):
        """
        创建房间
        使用: String(INCR), Hash(HSET)
        """
        r = get_redis_client()
        
        # 使用 String INCR 生成房间ID（如果room_id为空）
        if not room_id:
            room_id = str(r.incr("chat:config:room_counter"))
        
        # 使用 Hash 存储房间信息
        room_key = RoomManager._get_room_key(room_id)
        if r.exists(room_key):
            return {"success": False, "message": f"房间 {room_id} 已存在"}
        
        # Redis 3.x 兼容：逐个字段设置
        r.hset(room_key, "name", name)
        r.hset(room_key, "description", description)
        r.hset(room_key, "creator", creator)
        r.hset(room_key, "created_at", str(int(time.time())))
        
        # 初始化活跃度 ZSet
        r.zadd(RoomManager._get_activity_key(room_id), {room_id: time.time()})
        
        return {
            "success": True,
            "room_id": room_id,
            "name": name,
            "message": "房间创建成功"
        }
    
    @staticmethod
    def join_room(room_id, user_id, username=""):
        """
        加入房间
        使用: Set(SADD), Hash(HSET)
        """
        r = get_redis_client()
        room_key = RoomManager._get_room_key(room_id)
        
        # 检查房间是否存在
        if not r.exists(room_key):
            return {"success": False, "message": f"房间 {room_id} 不存在"}
        
        # 使用 Set 添加成员
        r.sadd(RoomManager._get_members_key(room_id), user_id)
        
        # 使用 Hash 存储用户在线状态（Redis 3.x 兼容）
        online_key = f"chat:online:user:{user_id}"
        r.hset(online_key, "user_id", user_id)
        r.hset(online_key, "username", username)
        r.hset(online_key, "room_id", room_id)
        r.hset(online_key, "login_time", str(int(time.time())))
        r.hset(online_key, "last_heartbeat", str(int(time.time())))
        
        # 使用 Set 记录全局在线用户
        r.sadd("chat:online:users", user_id)
        
        # 更新房间活跃度
        r.zadd(RoomManager._get_activity_key(room_id), {user_id: time.time()})
        
        return {
            "success": True,
            "message": f"{username or user_id} 加入房间 {room_id} 成功"
        }
    
    @staticmethod
    def leave_room(room_id, user_id):
        """
        离开房间
        使用: Set(SREM), Hash(HDEL)
        """
        r = get_redis_client()
        
        # 从房间成员中移除
        r.srem(RoomManager._get_members_key(room_id), user_id)
        
        # 更新用户房间列表
        r.srem(f"chat:set:user:{user_id}:rooms", room_id)
        
        return {
            "success": True,
            "message": f"用户 {user_id} 已离开房间 {room_id}"
        }
    
    @staticmethod
    def get_room_info(room_id):
        """
        获取房间信息
        使用: Hash(HGETALL)
        """
        r = get_redis_client()
        room_key = RoomManager._get_room_key(room_id)
        
        room_info = r.hgetall(room_key)
        if not room_info:
            return None
        
        # 获取成员数量
        member_count = r.scard(RoomManager._get_members_key(room_id))
        room_info["member_count"] = str(member_count)
        
        return room_info
    
    @staticmethod
    def get_room_members(room_id):
        """
        获取房间所有成员
        使用: Set(SMEMBERS)
        """
        r = get_redis_client()
        return r.smembers(RoomManager._get_members_key(room_id))
    
    @staticmethod
    def is_member(room_id, user_id):
        """
        检查用户是否是房间成员
        使用: Set(SISMEMBER)
        """
        r = get_redis_client()
        return r.sismember(RoomManager._get_members_key(room_id), user_id)
    
    @staticmethod
    def list_rooms():
        """
        列出所有房间
        使用: 扫描所有 chat:room:* 的 Hash
        """
        r = get_redis_client()
        rooms = []
        
        # 扫描所有房间
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match="chat:room:*", count=100)
            for key in keys:
                # 只处理房间 Hash（不是 members 或 activity）
                if ":members:" not in key and ":activity" not in key:
                    room_info = r.hgetall(key)
                    if room_info:
                        room_info["room_id"] = key.split(":")[2]
                        room_info["member_count"] = str(r.scard(f"{key}:members"))
                        rooms.append(room_info)
            
            if cursor == 0:
                break
        
        # 按创建时间排序
        rooms.sort(key=lambda x: int(x.get("created_at", 0)), reverse=True)
        return rooms
    
    @staticmethod
    def get_room_activity(room_id, start_time, end_time):
        """
        获取房间在指定时间范围内的活跃度
        使用: ZSet(ZRANGEBYSCORE)
        """
        r = get_redis_client()
        return r.zrangebyscore(
            RoomManager._get_activity_key(room_id),
            start_time,
            end_time
        )
    
    @staticmethod
    def delete_room(room_id):
        """
        删除房间
        使用: DEL
        """
        r = get_redis_client()
        
        # 获取所有成员，将他们从在线列表中移除
        members = RoomManager.get_room_members(room_id)
        for user_id in members:
            r.srem(f"chat:set:user:{user_id}:rooms", room_id)
        
        # 删除所有相关键
        r.delete(
            RoomManager._get_room_key(room_id),
            RoomManager._get_members_key(room_id),
            RoomManager._get_activity_key(room_id)
        )
        
        return {"success": True, "message": f"房间 {room_id} 已删除"}
