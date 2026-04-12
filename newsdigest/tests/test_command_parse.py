"""
命令解析测试
验证 BotPlatform.parse_command 的默认实现。
"""

from newsdigest.app.adapters.talkonly import TalkOnlyAdapter
from newsdigest.app.schemas.types import IncomingMessage


def _make_msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="talkonly",
        update_id=1,
        user_id=100,
        user_name="TestUser",
        chat_id=100,
        chat_type="private",
        text=text,
    )


def test_parse_subscribe_command():
    adapter = TalkOnlyAdapter()
    msg = _make_msg("/subscribe AI 09:00")
    cmd = adapter.parse_command(msg)
    assert cmd is not None
    assert cmd.name == "subscribe"
    assert cmd.args == ["AI", "09:00"]


def test_parse_command_with_bot_mention():
    adapter = TalkOnlyAdapter()
    msg = _make_msg("/help@NewsDigest")
    cmd = adapter.parse_command(msg)
    assert cmd is not None
    assert cmd.name == "help"


def test_non_command_returns_none():
    adapter = TalkOnlyAdapter()
    msg = _make_msg("hello world")
    cmd = adapter.parse_command(msg)
    assert cmd is None


def test_parse_digest_command():
    adapter = TalkOnlyAdapter()
    msg = _make_msg("/digest 人工智能")
    cmd = adapter.parse_command(msg)
    assert cmd is not None
    assert cmd.name == "digest"
    assert cmd.args == ["人工智能"]
