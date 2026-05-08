"""
聊天室主程序 - 基于Redis的命令行聊天室
支持多用户、多房间、实时消息
"""
import socket
import threading
import json
import time
import sys
from redis_client import redis_manager, get_redis_client
from room import RoomManager
from user import UserManager
from message import MessageManager
from config import SERVER_CONFIG


class ChatServer:
    """聊天室服务器"""

    def __init__(self, host=None, port=None):
        self.host = host or SERVER_CONFIG["host"]
        self.port = port or SERVER_CONFIG["port"]
        self.server_socket = None
        self.clients = {}  # {conn: {"user_id": ..., "room_id": ...}}
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        """启动服务器"""
        if not redis_manager.health_check():
            print("[错误] 无法连接到Redis，请检查Redis服务是否启动")
            return

        print(f"[服务器] 正在启动聊天室服务器 {self.host}:{self.port} ...")

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(50)
        self.running = True

        print(f"[服务器] 聊天室服务器已启动，监听 {self.host}:{self.port}")
        print("[服务器] 等待客户端连接...")

        heartbeat_thread = threading.Thread(target=self._heartbeat_checker, daemon=True)
        heartbeat_thread.start()

        try:
            while self.running:
                try:
                    conn, addr = self.server_socket.accept()
                    print(f"[服务器] 新连接来自 {addr}")
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True
                    )
                    client_thread.start()
                except OSError:
                    break
        except KeyboardInterrupt:
            print("\n[服务器] 正在关闭服务器...")
        finally:
            self.stop()

    def stop(self):
        """停止服务器"""
        self.running = False
        with self.lock:
            for conn in list(self.clients.keys()):
                try:
                    self._send(conn, {"type": "system", "content": "服务器已关闭"})
                    conn.close()
                except Exception:
                    pass
        if self.server_socket:
            self.server_socket.close()
        print("[服务器] 服务器已关闭")

    def _handle_client(self, conn, addr):
        """处理客户端连接"""
        buffer = ""
        try:
            while self.running:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        request = json.loads(line)
                        self._process_request(conn, request)
                    except json.JSONDecodeError:
                        self._send(conn, {"type": "error", "content": "无效的JSON格式"})
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self._handle_disconnect(conn)

    def _process_request(self, conn, request):
        """处理客户端请求"""
        action = request.get("action")
        handlers = {
            "login": self._handle_login,
            "logout": self._handle_logout,
            "create_room": self._handle_create_room,
            "join_room": self._handle_join_room,
            "leave_room": self._handle_leave_room,
            "list_rooms": self._handle_list_rooms,
            "send_message": self._handle_send_message,
            "get_messages": self._handle_get_messages,
            "get_online_users": self._handle_get_online_users,
            "get_room_members": self._handle_get_room_members,
            "heartbeat": self._handle_heartbeat,
            "leaderboard": self._handle_leaderboard,
            "search_by_tag": self._handle_search_by_tag,
            "user_info": self._handle_user_info,
        }
        handler = handlers.get(action)
        if handler:
            handler(conn, request)
        else:
            self._send(conn, {"type": "error", "content": f"未知操作: {action}"})

    def _handle_login(self, conn, request):
        """处理登录"""
        user_id = request.get("user_id", "")
        username = request.get("username", "")
        if not user_id:
            self._send(conn, {"type": "error", "content": "用户ID不能为空"})
            return

        result = UserManager.login(user_id, username)
        if result["success"]:
            with self.lock:
                self.clients[conn] = {"user_id": user_id, "room_id": ""}
            user_info = UserManager.get_user_info(user_id)
            self._send(conn, {
                "type": "login_success",
                "user_id": user_id,
                "username": user_info.get("username", username),
                "message": result["message"]
            })
            self._broadcast_system_message(None, f"用户 {username or user_id} 上线了")
        else:
            self._send(conn, {"type": "error", "content": result["message"]})

    def _handle_logout(self, conn, request=None):
        """处理登出"""
        with self.lock:
            client_info = self.clients.get(conn)
        if client_info:
            user_id = client_info["user_id"]
            room_id = client_info.get("room_id", "")
            username = ""
            user_info = UserManager.get_user_info(user_id)
            if user_info:
                username = user_info.get("username", user_id)
            if room_id:
                RoomManager.leave_room(room_id, user_id)
                self._broadcast_room_message(room_id, {
                    "type": "system",
                    "content": f"用户 {username} 离开了房间",
                    "room_id": room_id
                })
            UserManager.logout(user_id)
            with self.lock:
                if conn in self.clients:
                    del self.clients[conn]
            self._send(conn, {"type": "logout_success", "message": "已登出"})
            self._broadcast_system_message(None, f"用户 {username} 下线了")

    def _handle_create_room(self, conn, request):
        """处理创建房间"""
        client_info = self._get_client_info(conn)
        if not client_info:
            self._send(conn, {"type": "error", "content": "请先登录"})
            return
        room_id = request.get("room_id", "")
        room_name = request.get("room_name", "")
        description = request.get("description", "")
        creator = client_info["user_id"]
        result = RoomManager.create_room(room_id, room_name, description, creator)
        self._send(conn, {"type": "create_room_result", **result})

    def _handle_join_room(self, conn, request):
        """处理加入房间"""
        client_info = self._get_client_info(conn)
        if not client_info:
            self._send(conn, {"type": "error", "content": "请先登录"})
            return
        room_id = request.get("room_id", "")
        user_id = client_info["user_id"]
        username = ""
        user_info = UserManager.get_user_info(user_id)
        if user_info:
            username = user_info.get("username", user_id)
        result = RoomManager.join_room(room_id, user_id, username)
        if result["success"]:
            with self.lock:
                if conn in self.clients:
                    self.clients[conn]["room_id"] = room_id
            UserManager.join_room(user_id, room_id)
            messages = MessageManager.get_recent_messages(room_id, 50)
            self._send(conn, {
                "type": "join_room_success",
                "room_id": room_id,
                "messages": messages,
                "message": result["message"]
            })
            self._broadcast_room_message(room_id, {
                "type": "system",
                "content": f"用户 {username} 加入了房间",
                "room_id": room_id
            })
        else:
            self._send(conn, {"type": "error", "content": result["message"]})

    def _handle_leave_room(self, conn, request=None):
        """处理离开房间"""
        client_info = self._get_client_info(conn)
        if not client_info:
            self._send(conn, {"type": "error", "content": "请先登录"})
            return
        room_id = client_info.get("room_id", "")
        if not room_id:
            self._send(conn, {"type": "error", "content": "你不在任何房间中"})
            return
        user_id = client_info["user_id"]
        username = ""
        user_info = UserManager.get_user_info(user_id)
        if user_info:
            username = user_info.get("username", user_id)
        result = RoomManager.leave_room(room_id, user_id)
        with self.lock:
            if conn in self.clients:
                self.clients[conn]["room_id"] = ""
        self._send(conn, {"type": "leave_room_success", "message": result["message"]})
        self._broadcast_room_message(room_id, {
            "type": "system",
            "content": f"用户 {username} 离开了房间",
            "room_id": room_id
        })

    def _handle_list_rooms(self, conn, request=None):
        """处理列出房间"""
        rooms = RoomManager.list_rooms()
        self._send(conn, {"type": "room_list", "rooms": rooms})

    def _handle_send_message(self, conn, request):
        """处理发送消息"""
        client_info = self._get_client_info(conn)
        if not client_info:
            self._send(conn, {"type": "error", "content": "请先登录"})
            return
        room_id = client_info.get("room_id", "")
        if not room_id:
            self._send(conn, {"type": "error", "content": "请先加入房间"})
            return
        content = request.get("content", "")
        tags = request.get("tags", None)
        user_id = client_info["user_id"]
        username = ""
        user_info = UserManager.get_user_info(user_id)
        if user_info:
            username = user_info.get("username", user_id)
        if not content.strip():
            self._send(conn, {"type": "error", "content": "消息内容不能为空"})
            return
        result = MessageManager.send_message(room_id, user_id, username, content, tags)
        if result["success"]:
            msg = MessageManager.get_message(result["msg_id"])
            if msg:
                self._broadcast_room_message(room_id, {"type": "message", **msg})
        else:
            self._send(conn, {"type": "error", "content": result["message"]})

    def _handle_get_messages(self, conn, request):
        """处理获取消息"""
        client_info = self._get_client_info(conn)
        if not client_info:
            self._send(conn, {"type": "error", "content": "请先登录"})
            return
        room_id = request.get("room_id", client_info.get("room_id", ""))
        count = request.get("count", 50)
        if not room_id:
            self._send(conn, {"type": "error", "content": "请指定房间ID或先加入房间"})
            return
        messages = MessageManager.get_recent_messages(room_id, count)
        self._send(conn, {"type": "message_list", "room_id": room_id, "messages": messages})

    def _handle_get_online_users(self, conn, request=None):
        """处理获取在线用户"""
        users = UserManager.get_online_users()
        self._send(conn, {"type": "online_users", "users": users})

    def _handle_get_room_members(self, conn, request):
        """处理获取房间成员"""
        room_id = request.get("room_id", "")
        if not room_id:
            client_info = self._get_client_info(conn)
            if client_info:
                room_id = client_info.get("room_id", "")
        if not room_id:
            self._send(conn, {"type": "error", "content": "请指定房间ID"})
            return
        members = RoomManager.get_room_members(room_id)
        self._send(conn, {"type": "room_members", "room_id": room_id, "members": list(members)})

    def _handle_heartbeat(self, conn, request=None):
        """处理心跳"""
        client_info = self._get_client_info(conn)
        if client_info:
            UserManager.heartbeat(client_info["user_id"])
            self._send(conn, {"type": "heartbeat_ack"})

    def _handle_leaderboard(self, conn, request):
        """处理排行榜"""
        room_id = request.get("room_id", "")
        if not room_id:
            client_info = self._get_client_info(conn)
            if client_info:
                room_id = client_info.get("room_id", "")
        if not room_id:
            self._send(conn, {"type": "error", "content": "请指定房间ID"})
            return
        leaderboard = MessageManager.get_leaderboard(room_id)
        self._send(conn, {"type": "leaderboard", "room_id": room_id, "leaderboard": leaderboard})

    def _handle_search_by_tag(self, conn, request):
        """处理按标签搜索"""
        room_id = request.get("room_id", "")
        tags = request.get("tags", [])
        if not room_id:
            client_info = self._get_client_info(conn)
            if client_info:
                room_id = client_info.get("room_id", "")
        if not room_id:
            self._send(conn, {"type": "error", "content": "请指定房间ID"})
            return
        messages = MessageManager.get_messages_by_tags(room_id, tags)
        self._send(conn, {"type": "search_result", "room_id": room_id, "messages": messages})

    def _handle_user_info(self, conn, request):
        """处理获取用户信息"""
        user_id = request.get("user_id", "")
        if not user_id:
            client_info = self._get_client_info(conn)
            if client_info:
                user_id = client_info["user_id"]
        if not user_id:
            self._send(conn, {"type": "error", "content": "请指定用户ID"})
            return
        user_info = UserManager.get_user_info(user_id)
        msg_count = UserManager.get_msg_count(user_id)
        user_rooms = UserManager.get_user_rooms(user_id)
        self._send(conn, {
            "type": "user_info",
            "user_info": user_info,
            "message_count": msg_count,
            "rooms": list(user_rooms)
        })

    # ========== 辅助方法 ==========

    def _get_client_info(self, conn):
        """获取客户端信息"""
        with self.lock:
            return self.clients.get(conn)

    def _send(self, conn, data):
        """发送数据给客户端"""
        try:
            msg = json.dumps(data, ensure_ascii=False) + "\n"
            conn.sendall(msg.encode("utf-8"))
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _broadcast_room_message(self, room_id, data):
        """广播消息给房间内所有用户"""
        with self.lock:
            for conn, info in self.clients.items():
                if info.get("room_id") == room_id:
                    self._send(conn, data)

    def _broadcast_system_message(self, room_id, content):
        """广播系统消息"""
        data = {"type": "system", "content": content}
        with self.lock:
            for conn, info in self.clients.items():
                if room_id is None or info.get("room_id") == room_id:
                    self._send(conn, data)

    def _handle_disconnect(self, conn):
        """处理客户端断开连接"""
        with self.lock:
            client_info = self.clients.pop(conn, None)
        if client_info:
            user_id = client_info["user_id"]
            room_id = client_info.get("room_id", "")
            username = ""
            user_info = UserManager.get_user_info(user_id)
            if user_info:
                username = user_info.get("username", user_id)
            if room_id:
                RoomManager.leave_room(room_id, user_id)
                self._broadcast_room_message(room_id, {
                    "type": "system",
                    "content": f"用户 {username} 离开了房间",
                    "room_id": room_id
                })
            UserManager.logout(user_id)
            self._broadcast_system_message(None, f"用户 {username} 下线了")
        try:
            conn.close()
        except Exception:
            pass

    def _heartbeat_checker(self):
        """心跳检测线程"""
        while self.running:
            time.sleep(30)
            UserManager.get_online_users()  # 自动清理超时用户


class ChatClient:
    """聊天室客户端"""

    def __init__(self, host="127.0.0.1", port=6380):
        self.host = host
        self.port = port
        self.socket = None
        self.user_id = ""
        self.username = ""
        self.room_id = ""
        self.running = False
        self.receive_thread = None

    def connect(self):
        """连接服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_messages, daemon=True)
            self.receive_thread.start()
            return True
        except ConnectionRefusedError:
            print("[错误] 无法连接到服务器，请检查服务器是否启动")
            return False

    def disconnect(self):
        """断开连接"""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass

    def login(self, user_id, username):
        """登录"""
        self.user_id = user_id
        self.username = username
        self._send({"action": "login", "user_id": user_id, "username": username})

    def logout(self):
        """登出"""
        self._send({"action": "logout"})

    def create_room(self, room_id, room_name, description=""):
        """创建房间"""
        self._send({
            "action": "create_room",
            "room_id": room_id,
            "room_name": room_name,
            "description": description
        })

    def join_room(self, room_id):
        """加入房间"""
        self.room_id = room_id
        self._send({"action": "join_room", "room_id": room_id})

    def leave_room(self):
        """离开房间"""
        self._send({"action": "leave_room"})
        self.room_id = ""

    def list_rooms(self):
        """列出房间"""
        self._send({"action": "list_rooms"})

    def send_message(self, content, tags=None):
        """发送消息"""
        data = {"action": "send_message", "content": content}
        if tags:
            data["tags"] = tags
        self._send(data)

    def get_messages(self, room_id="", count=50):
        """获取消息"""
        self._send({"action": "get_messages", "room_id": room_id, "count": count})

    def get_online_users(self):
        """获取在线用户"""
        self._send({"action": "get_online_users"})

    def get_room_members(self, room_id=""):
        """获取房间成员"""
        self._send({"action": "get_room_members", "room_id": room_id})

    def get_leaderboard(self, room_id=""):
        """获取排行榜"""
        self._send({"action": "leaderboard", "room_id": room_id})

    def search_by_tag(self, tags, room_id=""):
        """按标签搜索"""
        self._send({"action": "search_by_tag", "tags": tags, "room_id": room_id})

    def get_user_info(self, user_id=""):
        """获取用户信息"""
        self._send({"action": "user_info", "user_id": user_id})

    def _send(self, data):
        """发送数据"""
        try:
            msg = json.dumps(data, ensure_ascii=False) + "\n"
            self.socket.sendall(msg.encode("utf-8"))
        except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
            print(f"[错误] 发送失败: {e}")

    def _receive_messages(self):
        """接收消息线程"""
        buffer = ""
        try:
            while self.running:
                data = self.socket.recv(4096)
                if not data:
                    print("\n[系统] 与服务器断开连接")
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            self._display_message(msg)
                        except json.JSONDecodeError:
                            pass
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            print("\n[系统] 与服务器断开连接")

    def _display_message(self, msg):
        """显示消息"""
        msg_type = msg.get("type")
        
        if msg_type == "message":
            username = msg.get("username", "未知")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", 0)
            time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
            print(f"\n[{time_str}] {username}: {content}")
        
        elif msg_type == "system":
            content = msg.get("content", "")
            print(f"\n[系统] {content}")
        
        elif msg_type == "login_success":
            print(f"\n[系统] 登录成功! 用户: {msg.get('username')}")
        
        elif msg_type == "logout_success":
            print(f"\n[系统] 已登出")
        
        elif msg_type == "create_room_result":
            if msg.get("success"):
                print(f"\n[系统] 房间创建成功! 房间ID: {msg.get('room_id')}")
            else:
                print(f"\n[系统] 房间创建失败: {msg.get('message')}")
        
        elif msg_type == "join_room_success":
            messages = msg.get("messages", [])
            print(f"\n[系统] 加入房间成功! 历史消息({len(messages)}条):")
            for m in messages:
                ts = time.strftime("%H:%M:%S", time.localtime(m.get("timestamp", 0)))
                print(f"  [{ts}] {m.get('username', '未知')}: {m.get('content', '')}")
        
        elif msg_type == "leave_room_success":
            print(f"\n[系统] 已离开房间")
        
        elif msg_type == "room_list":
            rooms = msg.get("rooms", [])
            print(f"\n[系统] 房间列表({len(rooms)}个):")
            for room in rooms:
                print(f"  房间ID: {room.get('room_id')}, 名称: {room.get('name')}, "
                      f"成员数: {room.get('member_count', 0)}")
        
        elif msg_type == "message_list":
            messages = msg.get("messages", [])
            print(f"\n[系统] 消息列表({len(messages)}条):")
            for m in messages:
                ts = time.strftime("%H:%M:%S", time.localtime(m.get("timestamp", 0)))
                print(f"  [{ts}] {m.get('username', '未知')}: {m.get('content', '')}")
        
        elif msg_type == "online_users":
            users = msg.get("users", [])
            print(f"\n[系统] 在线用户({len(users)}人):")
            for u in users:
                print(f"  {u.get('username', u.get('user_id', '未知'))}")
        
        elif msg_type == "room_members":
            members = msg.get("members", [])
            print(f"\n[系统] 房间成员({len(members)}人):")
            for m in members:
                print(f"  {m}")
        
        elif msg_type == "leaderboard":
            leaderboard = msg.get("leaderboard", [])
            print(f"\n[系统] 消息排行榜:")
            for i, entry in enumerate(leaderboard):
                print(f"  {i+1}. {entry.get('username')} - {entry.get('message_count')}条消息")
        
        elif msg_type == "search_result":
            messages = msg.get("messages", [])
            print(f"\n[系统] 搜索结果({len(messages)}条):")
            for m in messages:
                ts = time.strftime("%H:%M:%S", time.localtime(m.get("timestamp", 0)))
                print(f"  [{ts}] {m.get('username', '未知')}: {m.get('content', '')}")
        
        elif msg_type == "user_info":
            info = msg.get("user_info", {})
            print(f"\n[系统] 用户信息:")
            print(f"  用户ID: {info.get('user_id')}")
            print(f"  用户名: {info.get('username')}")
            print(f"  消息数: {msg.get('message_count', 0)}")
            print(f"  加入房间: {', '.join(msg.get('rooms', []))}")
        
        elif msg_type == "error":
            print(f"\n[错误] {msg.get('content')}")
        
        elif msg_type == "heartbeat_ack":
            pass  # 心跳响应不显示
        
        print(f"\n[{self.username or '未登录'}@{self.room_id or '大厅'}] > ", end="", flush=True)


def run_client():
    """运行客户端交互界面"""
    print("=" * 50)
    print("       hik talk客户端")
    print("=" * 50)
    
    client = ChatClient()
    
    if not client.connect():
        return
    
    print("\n可用命令:")
    print("  /login <用户ID> <用户名>     - 登录")
    print("  /logout                      - 登出")
    print("  /create <房间ID> <房间名>    - 创建房间")
    print("  /join <房间ID>               - 加入房间")
    print("  /leave                       - 离开房间")
    print("  /rooms                       - 列出房间")
    print("  /members [房间ID]            - 查看房间成员")
    print("  /online                      - 查看在线用户")
    print("  /history [数量]              - 查看历史消息")
    print("  /leaderboard [房间ID]        - 查看排行榜")
    print("  /search <标签1,标签2>        - 按标签搜索")
    print("  /info [用户ID]               - 查看用户信息")
    print("  /quit                        - 退出")
    print("  其他内容直接发送为聊天消息")
    print("=" * 50)
    
    try:
        while True:
            try:
                user_input = input(f"\n[{client.username or '未登录'}@{client.room_id or '大厅'}] > ").strip()
            except EOFError:
                break
            
            if not user_input:
                continue
            
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=3)
                cmd = parts[0].lower()
                
                if cmd == "/login" and len(parts) >= 3:
                    client.login(parts[1], parts[2])
                elif cmd == "/logout":
                    client.logout()
                elif cmd == "/create" and len(parts) >= 3:
                    desc = parts[3] if len(parts) > 3 else ""
                    client.create_room(parts[1], parts[2], desc)
                elif cmd == "/join" and len(parts) >= 2:
                    client.join_room(parts[1])
                elif cmd == "/leave":
                    client.leave_room()
                elif cmd == "/rooms":
                    client.list_rooms()
                elif cmd == "/members":
                    room_id = parts[1] if len(parts) > 1 else ""
                    client.get_room_members(room_id)
                elif cmd == "/online":
                    client.get_online_users()
                elif cmd == "/history":
                    count = int(parts[1]) if len(parts) > 1 else 50
                    client.get_messages(count=count)
                elif cmd == "/leaderboard":
                    room_id = parts[1] if len(parts) > 1 else ""
                    client.get_leaderboard(room_id)
                elif cmd == "/search" and len(parts) >= 2:
                    tags = parts[1].split(",")
                    client.search_by_tag(tags)
                elif cmd == "/info":
                    user_id = parts[1] if len(parts) > 1 else ""
                    client.get_user_info(user_id)
                elif cmd == "/quit":
                    client.logout()
                    break
                else:
                    print("[系统] 未知命令或参数不足，输入 /help 查看帮助")
            else:
                # 普通聊天消息
                client.send_message(user_input)
    
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        print("\n[系统] 已退出聊天室")


def run_server():
    """运行服务器"""
    server = ChatServer()
    server.start()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        run_server()
    elif len(sys.argv) > 1 and sys.argv[1] == "client":
        run_client()
    else:
        print("用法:")
        print("  python chat_server.py server  - 启动服务器")
        print("  python chat_server.py client  - 启动客户端")
