#!/usr/bin/python3
"""
NewsDigest Bot 启动入口
供 launchd 直接调用，自动设置 PYTHONPATH。
"""
import sys
import os

# 确保项目根目录在 sys.path 中
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from newsdigest.main import main
import asyncio

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
