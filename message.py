"""
消息发送与存储模块
使用 Redis 数据结构: List, ZSet, String, Set, Hash
"""
import time
import json
from redis_client import get_redis_client
from config import RECENT_MESSAGES_LIMIT, MESSAGE_TTL


class MessageManager:
    """消息管理器"""
    
    # List: 房间最新消息队列
    # Key: chat:list:room:{room_id}:recent
    # Value: 消息ID列表（最近N条）
    
    # ZSet: 房间消息时间线
    # Key: chat:zset:room:{room_id}:timeline
    # Member: 消息ID
    # Score: 时间戳
    
    # String: 消息详情
    # Key: chat:msg:{msg_id}
    # Value: JSON格式的消息内容
    
    # Set: 消息标签
    # Key: chat:set:msg:{msg_id}:tags
    
    # ZSet: 用户消息排行
    # Key: chat:zset:room:{room_id}:leaderboard
    # Member: user_id
    # Score: 消息数量
    
    @staticmethod
    def _get_msg_key(msg_id):
        """获取消息 String 的 key"""
        return f"chat:msg:{msg_id}"
    
    @staticmethod
    def _get_recent_key(room_id):
        """获取房间最新消息 List 的 key"""
        return f"chat:list:room:{room_id}:recent"
    
    @staticmethod
    def _get_timeline_key(room_id):
        """获取房间消息时间线 ZSet 的 key"""
        return f"chat:zset:room:{room_id}:timeline"
    
    @staticmethod
    def _get_tags_key(msg_id):
        """获取消息标签 Set 的 key"""
        return f"chat:set:msg:{msg_id}:tags"
    
    @staticmethod
    def _get_leaderboard_key(room_id):
        """获取房间排行榜 ZSet 的 key"""
        return f"chat:zset:room:{room_id}:leaderboard"
    
    @staticmethod
    def send_message(room_id, user_id, username, content, tags=None):
        """
        发送消息
        使用: String(INCR/SET), List(LPUSH/LTRIM), ZSet(ZADD), Set(SADD), Hash(HINCRBY)
        
        流程:
        1. 使用 String INCR 生成消息ID
        2. 使用 String SET 存储消息详情（JSON格式）
        3. 使用 List LPUSH 添加到房间最新消息队列
        4. 使用 List LTRIM 限制消息队列长度
        5. 使用 ZSet ZADD 添加到房间消息时间线
        6. 使用 Set SADD 添加消息标签
        7. 使用 Hash HINCRBY 更新用户消息排行
        """
        r = get_redis_client()
        
        # 1. 生成消息ID（使用 String INCR）
        msg_id = str(r.incr("chat:config:msg_counter"))
        
        # 2. 构建消息内容
        timestamp = int(time.time())
        message = {
            "msg_id": msg_id,
            "room_id": room_id,
            "user_id": user_id,
            "username": username,
            "content": content,
            "timestamp": timestamp,
            "type": "text"  # 可以是 text, image, system 等
        }
        
        # 3. 使用 String SET 存储消息详情
        msg_key = MessageManager._get_msg_key(msg_id)
        r.set(msg_key, json.dumps(message, ensure_ascii=False))
        r.expire(msg_key, MESSAGE_TTL)  # 设置过期时间
        
        # 4. 使用 List LPUSH 添加到房间最新消息队列
        recent_key = MessageManager._get_recent_key(room_id)
        r.lpush(recent_key, msg_id)
        
        # 5. 使用 List LTRIM 限制消息队列长度
        r.ltrim(recent_key, 0, RECENT_MESSAGES_LIMIT - 1)
        
        # 6. 使用 ZSet ZADD 添加到房间消息时间线
        timeline_key = MessageManager._get_timeline_key(room_id)
        r.zadd(timeline_key, {msg_id: timestamp})
        
        # 7. 如果有标签，使用 Set SADD 添加标签
        if tags:
            tags_key = MessageManager._get_tags_key(msg_id)
            r.sadd(tags_key, *tags)
            # 同时将消息ID添加到每个标签的集合
            for tag in tags:
                r.sadd(f"chat:set:tag:{tag}:messages", msg_id)
        
        # 8. 更新用户消息排行（使用 Hash HINCRBY）
        leaderboard_key = MessageManager._get_leaderboard_key(room_id)
        r.hincrby(leaderboard_key, user_id, 1)
        
        # 9. 增加用户消息计数（使用 String INCR）
        from user import UserManager
        UserManager.increment_msg_count(user_id)
        
        # 10. 更新房间活跃度（使用 ZSet ZADD）
        from room import RoomManager
        r.zadd(RoomManager._get_activity_key(room_id), {msg_id: timestamp})
        
        return {
            "success": True,
            "msg_id": msg_id,
            "message": "消息发送成功"
        }
    
    @staticmethod
    def send_system_message(room_id, content):
        """
        发送系统消息
        """
        return MessageManager.send_message(
            room_id=room_id,
            user_id="system",
            username="系统",
            content=content,
            tags=["system"]
        )
    
    @staticmethod
    def get_recent_messages(room_id, count=50):
        """
        获取房间最新消息
        使用: List(LRANGE)
        """
        r = get_redis_client()
        recent_key = MessageManager._get_recent_key(room_id)
        
        # 获取最近的消息ID列表
        msg_ids = r.lrange(recent_key, 0, count - 1)
        
        # 反转列表（最新的在前面）
        msg_ids.reverse()
        
        # 获取消息详情
        messages = []
        for msg_id in msg_ids:
            msg_key = MessageManager._get_msg_key(msg_id)
            msg_data = r.get(msg_key)
            if msg_data:
                messages.append(json.loads(msg_data))
        
        return messages
    
    @staticmethod
    def get_messages_by_timeline(room_id, start_timestamp=0, count=50):
        """
        按时间线获取消息
        使用: ZSet(ZRANGEBYSCORE)
        """
        r = get_redis_client()
        timeline_key = MessageManager._get_timeline_key(room_id)
        
        # 获取指定时间范围后的消息ID
        msg_ids = r.zrangebyscore(timeline_key, start_timestamp, "+inf", start=0, num=count)
        
        # 获取消息详情
        messages = []
        for msg_id in msg_ids:
            msg_key = MessageManager._get_msg_key(msg_id)
            msg_data = r.get(msg_key)
            if msg_data:
                messages.append(json.loads(msg_data))
        
        return messages
    
    @staticmethod
    def get_message(msg_id):
        """
        获取单条消息
        使用: String(GET)
        """
        r = get_redis_client()
        msg_key = MessageManager._get_msg_key(msg_id)
        msg_data = r.get(msg_key)
        
        if msg_data:
            return json.loads(msg_data)
        return None
    
    @staticmethod
    def get_messages_by_tags(room_id, tags, count=50):
        """
        按标签获取消息
        使用: Set(SINTER/SMEMBERS)
        """
        r = get_redis_client()
        
        # 获取包含所有标签的消息ID（取交集）
        if tags:
            result_keys = [f"chat:set:tag:{tag}:messages" for tag in tags]
            msg_ids = r.sinter(result_keys)
        else:
            return []
        
        # 获取消息详情
        messages = []
        for msg_id in msg_ids[:count]:
            msg_key = MessageManager._get_msg_key(msg_id)
            msg_data = r.get(msg_key)
            if msg_data:
                msg = json.loads(msg_data)
                # 确保消息属于指定房间
                if msg.get("room_id") == room_id:
                    messages.append(msg)
        
        return messages
    
    @staticmethod
    def get_message_tags(msg_id):
        """
        获取消息的所有标签
        使用: Set(SMEMBERS)
        """
        r = get_redis_client()
        tags_key = MessageManager._get_tags_key(msg_id)
        return r.smembers(tags_key)
    
    @staticmethod
    def get_messages_by_user(room_id, user_id, count=50):
        """
        获取用户指定房间的消息
        使用: ZSet(ZRANGEBYSCORE)
        """
        r = get_redis_client()
        timeline_key = MessageManager._get_timeline_key(room_id)
        
        # 获取房间所有消息ID
        all_msg_ids = r.zrange(timeline_key, 0, -1)
        
        # 过滤出指定用户的消息
        user_messages = []
        for msg_id in all_msg_ids[-count:]:  # 取最近N条
            msg_key = MessageManager._get_msg_key(msg_id)
            msg_data = r.get(msg_key)
            if msg_data:
                msg = json.loads(msg_data)
                if msg.get("user_id") == user_id:
                    user_messages.append(msg)
        
        return user_messages[-count:]
    
    @staticmethod
    def get_leaderboard(room_id, start=0, end=9):
        """
        获取房间消息排行榜
        使用: ZSet(ZREVRANGE)
        """
        r = get_redis_client()
        leaderboard_key = MessageManager._get_leaderboard_key(room_id)
        
        # 获取排名前N的用户
        rankings = r.zrevrange(leaderboard_key, start, end, withscores=True)
        
        # 构建排行榜信息
        leaderboard = []
        for user_id, score in rankings:
            from user import UserManager
            user_info = UserManager.get_user_info(user_id)
            leaderboard.append({
                "user_id": user_id,
                "username": user_info.get("username") if user_info else user_id,
                "message_count": int(score)
            })
        
        return leaderboard
    
    @staticmethod
    def delete_message(msg_id):
        """
        删除消息
        """
        r = get_redis_client()
        msg_key = MessageManager._get_msg_key(msg_id)
        
        # 获取消息详情以便清理其他数据结构
        msg_data = r.get(msg_key)
        if not msg_data:
            return {"success": False, "message": "消息不存在"}
        
        msg = json.loads(msg_data)
        room_id = msg.get("room_id")
        
        # 删除消息详情
        r.delete(msg_key)
        
        # 从时间线中移除
        timeline_key = MessageManager._get_timeline_key(room_id)
        r.zrem(timeline_key, msg_id)
        
        # 从最新消息列表中移除
        recent_key = MessageManager._get_recent_key(room_id)
        r.lrem(recent_key, 0, msg_id)
        
        return {"success": True, "message": "消息删除成功"}
