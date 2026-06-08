from newbro.protocol import BroTimelineMessage
from newbro.runtime.bro_detail_thread_helpers import _mark_timeline_message_skill


def _msg():
    return BroTimelineMessage(message_id="test-msg-1", role="user", metadata={})


def test_marks_message_with_skill():
    marked = _mark_timeline_message_skill(_msg(), {"name": "doc", "display_name": "Word Docs"})
    assert marked.metadata["skill"] == {"name": "doc", "display_name": "Word Docs"}


def test_none_message_passthrough():
    assert _mark_timeline_message_skill(None, {"name": "doc"}) is None


def test_no_skill_returns_message_unchanged():
    msg = _msg()
    assert _mark_timeline_message_skill(msg, None) is msg
