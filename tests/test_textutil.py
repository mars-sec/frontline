from frontline.textutil import first_sentences, html_to_text


def test_html_to_text_strips_tags_and_entities():
    html = '<p>Hello <a href="x">world</a> &amp; <b>friends</b>.</p><p>Second&nbsp;line.</p>'
    out = html_to_text(html)
    assert "<" not in out and ">" not in out
    assert "&amp;" not in out
    assert "Hello world & friends." in out
    assert "Second" in out


def test_html_to_text_handles_empty_and_plain():
    assert html_to_text("") == ""
    assert html_to_text(None) == ""
    assert html_to_text("already plain text") == "already plain text"


def test_first_sentences_bounds():
    text = "First sentence here. Second one follows. Third is extra."
    out = first_sentences(text, max_sentences=2)
    assert out == "First sentence here. Second one follows."


def test_first_sentences_truncates_long():
    long = "word " * 200
    out = first_sentences(long, max_chars=100)
    assert len(out) <= 101
