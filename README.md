# hik talk

基于 Redis 的多房间实时聊天室，支持命令行和 Web 两种访问方式，充分利用 Redis 五种核心数据结构。

## 数据结构设计

| 数据结构 | 用途 | Redis Key 示例 |
|----------|------|----------------|
| **String** | 消息ID计数器、用户消息计数 | `chat:config:msg_counter`, `chat:config:user_msg_count:{user_id}` |
| **List** | 房间最新消息队列 | `chat:list:room:{room_id}:recent` |
| **Set** | 房间成员、消息标签、用户房间 | `chat:room:{room_id}:members`, `chat:set:msg:{msg_id}:tags` |
| **ZSet** | 消息时间线、活跃度、排行榜 | `chat:zset:room:{room_id}:timeline`, `chat:zset:room:{room_id}:leaderboard` |
| **Hash** | 房间信息、用户信息、消息详情 | `chat:room:{room_id}`, `chat:user:{user_id}`, `chat:msg:{msg_id}` |

## 环境要求

- Python 3.7+
- Redis 5.0+
- redis-py 库

## 安装

```bash
pip install redis
```

## 使用方法

### 1. 启动 Redis 服务

确保 Redis 服务已启动（默认端口 6379）。

### 2. 安装依赖

```bash
pip install redis flask
```

---

## Web 版（推荐）

### 启动 Web 服务器

```bash
python web_app.py
```

或双击 `start_web.bat`

然后在浏览器中访问: http://localhost:5000

### Web 版功能

- **用户注册/登录**: 新用户首次登录自动注册并保存密码
- **个人资料**: 修改用户名、头像
- **修改密码**: 安全修改账户密码
- **房间管理**: 创建房间、加入房间、查看房间列表
- **实时聊天**: 发送消息、查看历史消息
- **在线用户**: 查看当前在线用户列表
- **消息排行榜**: 查看房间消息发送排行

---

## 命令行版

### 启动聊天室服务器

```bash
python chat_server.py server
```

或双击 `start_server.bat`

### 启动客户端（可开多个终端）

```bash
python chat_server.py client
```

或双击 `start_client.bat`

## 客户端命令

| 命令 | 说明 |
|------|------|
| `/login <用户ID> <用户名>` | 登录 |
| `/create <房间ID> <房间名>` | 创建房间 |
| `/join <房间ID>` | 加入房间 |
| `/leave` | 离开当前房间 |
| `/rooms` | 列出所有房间 |
| `/members [房间ID]` | 查看房间成员 |
| `/online` | 查看在线用户 |
| `/history [数量]` | 查看历史消息 |
| `/leaderboard [房间ID]` | 查看消息排行榜 |
| `/search <标签1,标签2>` | 按标签搜索消息 |
| `/info [用户ID]` | 查看用户信息 |
| `/quit` | 退出聊天室 |
| 直接输入文字 | 发送聊天消息 |

## 使用示例

```
# 终端1 - 用户Alice
/login alice Alice
/create room1 技术交流
/join room1
大家好！

# 终端2 - 用户Bob
/login bob Bob
/join room1
你好 Alice！
```

## 项目结构

```
redis/
├── config.py          # 配置文件
├── redis_client.py    # Redis 连接管理
├── room.py            # 房间管理模块
├── user.py            # 用户管理模块
├── message.py         # 消息管理模块
├── chat_server.py     # 命令行服务器与客户端主程序
├── web_app.py         # Flask Web 应用
├── templates/         # HTML 模板
│   ├── login.html     # 登录页面
│   └── chat.html      # 聊天室页面
├── start_server.bat   # Windows 启动命令行服务器
├── start_client.bat   # Windows 启动命令行客户端
├── start_web.bat      # Windows 启动 Web 服务器
└── README.md          # 说明文档
```

## 配置说明

编辑 `config.py` 可修改：

- Redis 连接地址和端口
- 聊天室服务器端口（默认 6380）
- 消息保留数量（默认 500）
- 消息过期时间（默认 7 天）
- 心跳超时时间（默认 60 秒）
