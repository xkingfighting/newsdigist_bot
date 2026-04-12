#!/bin/bash
# NewsDigest Bot 启动脚本
cd /Users/x/Documents/Project/talkonly-bot
export PYTHONPATH="/Users/x/Documents/Project/talkonly-bot"
export PYTHONUNBUFFERED=1
exec /usr/bin/python3 -m newsdigest.main
