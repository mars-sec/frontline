from frontline.discover import _topics_hint, _proposed_feeds


def test_topics_hint_generic_returns_empty():
    assert _topics_hint(["Technology", "Other"]) == ""


def test_topics_hint_custom_sections():
    hint = _topics_hint(["Technology", "Cybersecurity", "AI Research"])
    assert "Cybersecurity" in hint
    assert "AI Research" in hint


def test_proposed_feeds_parses_json_block():
    reply = '```json\n[{"name":"X","url":"https://x.com/feed","why":"good"}]\n```'
    feeds = _proposed_feeds(reply)
    assert len(feeds) == 1
    assert feeds[0]["url"] == "https://x.com/feed"


def test_proposed_feeds_skips_missing_url():
    reply = '```json\n[{"name":"bad","why":"no url"}]\n```'
    assert _proposed_feeds(reply) == []


def test_proposed_feeds_no_json():
    assert _proposed_feeds("no json here at all") == []


def test_proposed_feeds_takes_last_block():
    reply = (
        '```json\n[{"name":"first","url":"https://a.com/feed"}]\n```\n'
        'some text\n'
        '```json\n[{"name":"second","url":"https://b.com/feed"}]\n```'
    )
    feeds = _proposed_feeds(reply)
    assert len(feeds) == 1
    assert feeds[0]["name"] == "second"
