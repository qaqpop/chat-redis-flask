"""
Flask Web 聊天室应用
支持登录、登出、用户密码记录、实时聊天
"""
import hashlib
import time
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from redis_client import redis_manager, get_redis_client
from room import RoomManager
from user import UserManager
from message import MessageManager

app = Flask(__name__)
app.secret_key = 'redis-chatroom-secret-key-2026'


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def hash_password(password):
    """密码哈希"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


@app.route('/')
def index():
    """首页，已登录则跳转到聊天室"""
    if 'user_id' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        user_id = request.form.get('user_id', '').strip()
        password = request.form.get('password', '').strip()
        username = request.form.get('username', '').strip()
        
        if not user_id or not password:
            flash('用户ID和密码不能为空', 'danger')
            return render_template('login.html')
        
        r = get_redis_client()
        user_key = f"chat:user:{user_id}"
        user_info = r.hgetall(user_key)
        
        if user_info:
            # 已有用户，验证密码
            stored_password = user_info.get('password', '')
            if stored_password != hash_password(password):
                flash('密码错误', 'danger')
                return render_template('login.html')
            # 使用存储的用户名
            display_username = user_info.get('username', user_id)
        else:
            # 新用户，自动注册
            if not username:
                username = user_id
            UserManager.register_user(user_id, username)
            # 保存密码
            r.hset(user_key, "password", hash_password(password))
            display_username = username
        
        # 登录
        UserManager.login(user_id, display_username)
        session['user_id'] = user_id
        session['username'] = display_username
        session.permanent = True
        
        flash(f'欢迎, {display_username}!', 'success')
        return redirect(url_for('chat'))
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    """登出"""
    user_id = session.get('user_id', '')
    if user_id:
        UserManager.logout(user_id)
    session.clear()
    flash('已登出', 'info')
    return redirect(url_for('login'))


@app.route('/chat')
@login_required
def chat():
    """聊天室页面"""
    user_id = session['user_id']
    username = session['username']
    
    # 获取用户当前所在房间
    r = get_redis_client()
    online_info = r.hgetall(f"chat:online:user:{user_id}")
    current_room = online_info.get('room_id', '') if online_info else ''
    
    # 获取所有房间列表
    rooms = RoomManager.list_rooms()
    
    # 获取用户加入的房间
    user_rooms = UserManager.get_user_rooms(user_id)
    
    return render_template('chat.html', 
                          user_id=user_id, 
                          username=username,
                          current_room=current_room,
                          rooms=rooms,
                          user_rooms=list(user_rooms))


@app.route('/api/rooms', methods=['GET'])
@login_required
def api_list_rooms():
    """API: 获取房间列表"""
    rooms = RoomManager.list_rooms()
    return jsonify({"success": True, "rooms": rooms})


@app.route('/api/rooms/create', methods=['POST'])
@login_required
def api_create_room():
    """API: 创建房间"""
    data = request.get_json()
    room_id = data.get('room_id', '')
    room_name = data.get('room_name', '')
    description = data.get('description', '')
    creator = session['user_id']
    
    result = RoomManager.create_room(room_id, room_name, description, creator)
    return jsonify(result)


@app.route('/api/rooms/join', methods=['POST'])
@login_required
def api_join_room():
    """API: 加入房间"""
    data = request.get_json()
    room_id = data.get('room_id', '')
    user_id = session['user_id']
    username = session['username']
    
    result = RoomManager.join_room(room_id, user_id, username)
    if result['success']:
        UserManager.join_room(user_id, room_id)
    
    return jsonify(result)


@app.route('/api/rooms/leave', methods=['POST'])
@login_required
def api_leave_room():
    """API: 离开房间"""
    data = request.get_json()
    room_id = data.get('room_id', '')
    user_id = session['user_id']
    
    result = RoomManager.leave_room(room_id, user_id)
    return jsonify(result)


@app.route('/api/rooms/<room_id>/members', methods=['GET'])
@login_required
def api_get_room_members(room_id):
    """API: 获取房间成员"""
    members = RoomManager.get_room_members(room_id)
    return jsonify({"success": True, "members": list(members)})


@app.route('/api/messages', methods=['GET'])
@login_required
def api_get_messages():
    """API: 获取消息"""
    room_id = request.args.get('room_id', '')
    count = int(request.args.get('count', 50))
    
    if not room_id:
        return jsonify({"success": False, "message": "请指定房间ID"})
    
    messages = MessageManager.get_recent_messages(room_id, count)
    return jsonify({"success": True, "messages": messages})


@app.route('/api/messages/send', methods=['POST'])
@login_required
def api_send_message():
    """API: 发送消息"""
    data = request.get_json()
    room_id = data.get('room_id', '')
    content = data.get('content', '')
    tags = data.get('tags', None)
    
    if not room_id:
        return jsonify({"success": False, "message": "请指定房间ID"})
    
    if not content.strip():
        return jsonify({"success": False, "message": "消息内容不能为空"})
    
    user_id = session['user_id']
    username = session['username']
    
    result = MessageManager.send_message(room_id, user_id, username, content, tags)
    return jsonify(result)


@app.route('/api/users/online', methods=['GET'])
@login_required
def api_get_online_users():
    """API: 获取在线用户"""
    users = UserManager.get_online_users()
    return jsonify({"success": True, "users": users})


@app.route('/api/users/info', methods=['GET'])
@login_required
def api_get_user_info():
    """API: 获取用户信息"""
    user_id = request.args.get('user_id', session['user_id'])
    user_info = UserManager.get_user_info(user_id)
    msg_count = UserManager.get_msg_count(user_id)
    user_rooms = UserManager.get_user_rooms(user_id)
    
    return jsonify({
        "success": True,
        "user_info": user_info,
        "message_count": msg_count,
        "rooms": list(user_rooms)
    })


@app.route('/api/leaderboard', methods=['GET'])
@login_required
def api_get_leaderboard():
    """API: 获取排行榜"""
    room_id = request.args.get('room_id', '')
    if not room_id:
        return jsonify({"success": False, "message": "请指定房间ID"})
    
    leaderboard = MessageManager.get_leaderboard(room_id)
    return jsonify({"success": True, "leaderboard": leaderboard})


@app.route('/api/search', methods=['GET'])
@login_required
def api_search_by_tag():
    """API: 按标签搜索"""
    room_id = request.args.get('room_id', '')
    tags = request.args.getlist('tags')
    
    if not room_id:
        return jsonify({"success": False, "message": "请指定房间ID"})
    
    messages = MessageManager.get_messages_by_tags(room_id, tags)
    return jsonify({"success": True, "messages": messages})


@app.route('/api/profile/update', methods=['POST'])
@login_required
def api_update_profile():
    """API: 更新个人资料"""
    data = request.get_json()
    username = data.get('username', '')
    avatar = data.get('avatar', '')
    
    if not username.strip():
        return jsonify({"success": False, "message": "用户名不能为空"})
    
    user_id = session['user_id']
    result = UserManager.update_user_info(user_id, username=username, avatar=avatar)
    
    if result['success']:
        session['username'] = username
    
    return jsonify(result)


@app.route('/api/profile/password', methods=['POST'])
@login_required
def api_change_password():
    """API: 修改密码"""
    data = request.get_json()
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    
    if not old_password or not new_password:
        return jsonify({"success": False, "message": "请填写完整"})
    
    user_id = session['user_id']
    r = get_redis_client()
    user_key = f"chat:user:{user_id}"
    user_info = r.hgetall(user_key)
    
    if not user_info:
        return jsonify({"success": False, "message": "用户不存在"})
    
    stored_password = user_info.get('password', '')
    if stored_password != hash_password(old_password):
        return jsonify({"success": False, "message": "原密码错误"})
    
    # 更新密码
    r.hset(user_key, "password", hash_password(new_password))
    return jsonify({"success": True, "message": "密码修改成功"})


if __name__ == '__main__':
    # 检查 Redis 连接
    if not redis_manager.health_check():
        print("[错误] 无法连接到 Redis，请检查 Redis 服务是否启动")
        exit(1)
    
    print("[服务器] Flask Web 聊天室启动中...")
    app.run(host='0.0.0.0', port=5000, debug=True)
