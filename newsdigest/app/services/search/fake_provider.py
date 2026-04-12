"""
Fake 搜索 Provider
用于本地开发和无网络环境下的测试。
返回差异化的模拟资讯数据，每个关键词有独立内容，避免模板化输出。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from newsdigest.app.schemas.types import NewsItem
from newsdigest.app.services.search.base import SearchProvider

# 按关键词预定义不同内容，避免所有关键词生成雷同摘要
_FAKE_DATA: dict[str, list[dict]] = {
    "AI": [
        {"title": "Google DeepMind 发布 Gemini 2.0 多模态模型", "snippet": "Google DeepMind 正式发布 Gemini 2.0，支持文本、图像、音频和视频四种模态输入。基准测试显示其在 MMLU 上达到 92.3 分，超越 GPT-4o 的 91.1 分。模型将于下月向开发者开放 API。", "source": "TechCrunch"},
        {"title": "欧盟 AI 法案正式生效，全球首部 AI 监管法律落地", "snippet": "欧盟《人工智能法案》于本月 1 日正式生效，将 AI 系统按风险等级分为四类。高风险 AI（如招聘筛选、信用评估）须通过合规审查，违规企业最高罚款 3500 万欧元或全球营收 7%。", "source": "Reuters"},
        {"title": "百度文心一言日调用量突破 5 亿次", "snippet": "百度披露文心一言最新运营数据：日均 API 调用量达 5.2 亿次，较三个月前增长 120%。企业客户超 18 万家，覆盖金融、医疗、制造等行业。百度同时宣布文心 4.5 turbo 版本降价 60%。", "source": "36氪"},
    ],
    "小米": [
        {"title": "小米 SU7 Ultra 量产版正式下线，售价 52.99 万元", "snippet": "小米汽车宣布 SU7 Ultra 量产版在北京亦庄工厂正式下线。该车搭载双电机四驱系统，零百加速 1.98 秒，CLTC 续航 630 公里。首批交付将于 4 月底开始，目前订单超 3 万台。", "source": "汽车之家"},
        {"title": "小米 15 Ultra 海外发售，DXOMark 影像评分第一", "snippet": "小米 15 Ultra 在欧洲和东南亚正式开售，搭载一英寸传感器主摄与徕卡光学镜头。DXOMark 给出 157 分综合评分，超越 iPhone 16 Pro Max 和三星 S25 Ultra，位列第一。", "source": "GSMArena"},
        {"title": "小米集团 Q4 财报：营收 1090 亿元同比增长 49%", "snippet": "小米发布 2025 财年 Q4 财报，单季营收 1090 亿元人民币，同比增长 49%。其中智能电动汽车业务贡献 198 亿元。智能手机出货量 4150 万台，全球市场份额升至 14.1%。", "source": "第一财经"},
    ],
    "特斯拉": [
        {"title": "特斯拉 Robotaxi 获旧金山运营许可", "snippet": "加州公用事业委员会批准特斯拉在旧金山开展 Robotaxi 商业运营试点。初期投放 100 辆 Model 3 改装车，运营时间为早 6 点至晚 10 点，服务区域覆盖市中心 15 平方英里。", "source": "Bloomberg"},
        {"title": "特斯拉上海储能超级工厂投产，年产 Megapack 1 万台", "snippet": "特斯拉上海储能超级工厂举行投产仪式，设计年产能 1 万台 Megapack，单台容量 3.9MWh。工厂投资约 14.5 亿元，产品将供应亚太和欧洲市场。", "source": "新华社"},
        {"title": "马斯克称 FSD V13 将在 Q3 推送全球市场", "snippet": "马斯克在财报电话会上表示，FSD（完全自动驾驶）V13 版本已在北美完成 50 万英里路测，事故率低于人类驾驶员 60%。计划于 Q3 推送至中国、欧洲等市场，前提是通过当地监管审批。", "source": "Electrek"},
    ],
}

# 通用兜底数据（未命中关键词时使用）
_DEFAULT_DATA = [
    {"title": "联合国发布 2026 年可持续发展报告", "snippet": "联合国经济与社会事务部发布年度报告，指出全球可再生能源装机容量在 2025 年突破 4.5TW，但仍有 23 个国家未达到巴黎协定减排目标。报告建议加速碳交易市场建设。", "source": "UN News"},
    {"title": "苹果 WWDC 2026 确认 6 月 9 日召开", "snippet": "苹果官方宣布 WWDC 2026 将于 6 月 9 日至 13 日在 Apple Park 举行。外界预计将发布 iOS 20、macOS 17 以及新一代 Apple Intelligence 功能。开发者注册已开放。", "source": "The Verge"},
    {"title": "全球半导体行业 Q1 营收达 1920 亿美元", "snippet": "SIA（半导体行业协会）数据显示，2026 年 Q1 全球半导体营收 1920 亿美元，同比增长 21%。其中 AI 芯片占比首次超过 30%，英伟达以 38% 市场份额保持领先。", "source": "SIA"},
]


class FakeSearchProvider(SearchProvider):
    """返回差异化模拟数据的搜索 Provider，用于离线测试。"""

    @property
    def provider_name(self) -> str:
        return "fake"

    async def search(self, keyword: str, max_results: int = 8) -> list[NewsItem]:
        now = datetime.utcnow()

        # 查找关键词对应的数据，未命中则用通用数据
        raw_items = _FAKE_DATA.get(keyword, _DEFAULT_DATA)

        items: list[NewsItem] = []
        for i, data in enumerate(raw_items[:max_results]):
            items.append(NewsItem(
                title=data["title"],
                snippet=data["snippet"],
                source=data.get("source", ""),
                url=f"https://example.com/news/{keyword}/{i+1}",
                published_at=now - timedelta(hours=(i + 1) * 3),
            ))

        return items
