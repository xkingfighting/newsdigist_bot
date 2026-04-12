# NewsDigest Bot

基于 TalkOnly 平台的每日资讯订阅 Bot。用户可订阅关键词，系统定时抓取网络资讯并通过本地大模型生成摘要推送。

## 架构概览

```
MVC + Adapter + Service + Repository 分层架构

┌─────────────────────────────────────────────────────┐
│                    main.py                          │
│              (启动 / 生命周期管理)                     │
├─────────────────────────────────────────────────────┤
│  Controllers    │  命令路由与参数校验                   │
├─────────────────────────────────────────────────────┤
│  Services       │  业务逻辑层                         │
│  - SubscriptionService  订阅管理                     │
│  - DigestService        摘要流程编排                  │
│  - SummarizerService    Ollama 摘要                  │
│  - SearchProvider       资讯抓取 (可插拔)              │
├─────────────────────────────────────────────────────┤
│  Repositories   │  数据访问层 (SQLAlchemy async)       │
├─────────────────────────────────────────────────────┤
│  Adapters       │  平台适配层 (TalkOnly / 未来扩展)     │
├─────────────────────────────────────────────────────┤
│  Core           │  配置 / 日志 / DB / Redis            │
└─────────────────────────────────────────────────────┘
```

## 环境要求

- Python 3.12+
- MySQL 8.0+
- Redis 6.0+
- Ollama (本地运行，默认模型 qwen2.5:7b)

## 快速开始

### 1. 安装依赖

```bash
cd newsdigest
python -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt
```

> requirements.txt 在项目根目录 (talkonly-bot/)。

### 2. 配置环境变量

```bash
cp ../.env.example ../.env
# 编辑 .env，填写实际的 MySQL / Redis / TalkOnly 配置
```

### 3. 初始化数据库

```bash
# 使用 root 账号执行初始化 SQL
mysql -u root -p < database/init.sql
```

### 4. 确保 Ollama 运行

```bash
# 拉取模型
ollama pull qwen2.5:7b

# 确认 Ollama 在运行
curl http://127.0.0.1:11434/api/tags
```

### 5. 启动 Bot

```bash
# 在项目根目录 talkonly-bot/ 下运行
python -m newsdigest.main
```

Bot 启动后会：
1. 切换到 Polling 模式 (deleteWebhook)
2. 从数据库恢复所有活跃订阅的定时任务
3. 开始长轮询循环

### 6. 测试 /digest

在 TalkOnly 中向 Bot 发送：

```
/digest AI
```

Bot 会立即抓取 AI 相关资讯，调用 Ollama 生成摘要并返回。

> 开发模式 (APP_DEBUG=true, APP_ENV=development) 下默认使用 FakeSearchProvider，无需联网。

## Bot 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| /start | 欢迎与功能说明 | /start |
| /help | 命令帮助 | /help |
| /subscribe | 创建订阅 | /subscribe AI 09:00 |
| /list | 查看所有订阅 | /list |
| /unsubscribe | 取消订阅 | /unsubscribe AI |
| /pause | 暂停订阅 | /pause AI |
| /resume | 恢复订阅 | /resume AI |
| /digest | 立即获取摘要 | /digest AI |

## 运行测试

```bash
# 在项目根目录
pip install pytest pytest-asyncio
python -m pytest newsdigest/tests/ -v
```

测试包含：
- 搜索结果去重/过滤
- Summarizer prompt 构建与兜底
- FakeProvider 行为
- 命令解析
- 集成测试（FakeProvider + MockSummarizer）

## 项目结构

```
newsdigest/
├── app/
│   ├── adapters/          # 平台适配层
│   │   ├── base.py        # BotPlatform 抽象接口
│   │   └── talkonly.py    # TalkOnly 实现
│   ├── controllers/       # 命令控制器
│   │   └── command_handler.py
│   ├── core/              # 基础设施
│   │   ├── config.py      # 配置加载
│   │   ├── database.py    # MySQL async engine
│   │   ├── logging.py     # 统一日志
│   │   └── redis.py       # Redis 连接
│   ├── models/            # ORM 模型
│   │   └── orm.py
│   ├── repositories/      # 数据访问层
│   │   ├── offset_repo.py
│   │   ├── push_log_repo.py
│   │   ├── subscription_repo.py
│   │   └── user_repo.py
│   ├── schedulers/        # 定时调度
│   │   └── digest_scheduler.py
│   ├── schemas/           # 共享数据结构
│   │   └── types.py
│   └── services/          # 业务逻辑
│       ├── digest_service.py
│       ├── subscription_service.py
│       ├── summarizer.py
│       └── search/
│           ├── base.py           # SearchProvider 抽象
│           ├── google_news.py    # Google News RSS 实现
│           └── fake_provider.py  # 离线测试 Provider
├── config/
├── database/
│   └── init.sql           # 建库建表 SQL
├── storage/
│   └── logs/
├── tests/                 # 测试
├── main.py                # 主入口
└── README.md
```

## 扩展指南

### 添加新的平台适配器

1. 在 `app/adapters/` 下创建新文件，如 `telegram.py`
2. 继承 `BotPlatform` 抽象类
3. 实现所有抽象方法：`get_updates`, `send_message`, `send_typing`, `start`, `stop`
4. 在 `main.py` 中根据配置选择适配器实例

```python
from newsdigest.app.adapters.base import BotPlatform

class TelegramAdapter(BotPlatform):
    @property
    def platform_name(self) -> str:
        return "telegram"

    async def get_updates(self, offset: int) -> list[IncomingMessage]:
        # Telegram Bot API 实现
        ...

    async def send_message(self, chat_id: int, text: str, chat_type: str = "private") -> bool:
        ...
```

### 添加新的 SearchProvider

1. 在 `app/services/search/` 下创建新文件
2. 继承 `SearchProvider` 抽象类
3. 实现 `search()` 方法，返回 `list[NewsItem]`
4. 在 `main.py` 中切换 Provider

```python
from newsdigest.app.services.search.base import SearchProvider

class TavilyProvider(SearchProvider):
    @property
    def provider_name(self) -> str:
        return "tavily"

    async def search(self, keyword: str, max_results: int = 8) -> list[NewsItem]:
        # Tavily API 实现
        ...
```

### 替换本地模型

修改 `.env` 中的 `OLLAMA_MODEL` 即可切换模型：

```env
OLLAMA_MODEL=llama3:8b
```

如需替换为远程 API（如 OpenAI），继承或修改 `SummarizerService`，替换 `_call_ollama` 方法。
