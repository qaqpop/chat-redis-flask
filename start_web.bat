@echo off
echo 正在启动 Redis Web 聊天室...
pip install flask >nul 2>&1
python web_app.py
pause