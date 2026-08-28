# tests/test_render.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import render as R  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def test_parse_minutes_polished():
    data = R.parse_minutes_md((FIX / "minutes_polished.md").read_text(encoding="utf-8"))
    ch = data["chapters"]
    assert len(ch) == 9
    assert ch[0]["title"].startswith("一、开场交流")
    assert any(e["speaker"] == "demo 张三" and "–" in e["ts"] for c in ch for e in c["entries"])
    assert sum(len(c["entries"]) for c in ch) == 53


def test_parse_minutes_raw_no_chapters():
    data = R.parse_minutes_md((FIX / "minutes_raw.md").read_text(encoding="utf-8"))
    ch = data["chapters"]
    assert len(ch) == 1 and ch[0]["title"] == "发言记录"
    assert len(ch[0]["entries"]) == 150


def test_md_inline_and_doc():
    assert R.md_inline("**a**b<c") == "<strong>a</strong>b&lt;c"
    html = R.parse_doc_md("# T\n\n## S\n\n- x\n\n> q\n\ntext **b**\n\n---\n")
    assert "<h1" in html and "<h2" in html and "<li>x</li>" in html
    assert "<blockquote" in html and "<hr" in html and "<strong>b</strong>" in html


def test_expand_simple_and_if():
    assert R.expand("<t>{{TITLE}}</t>", {"TITLE": "A"}) == "<t>A</t>"
    assert R.expand("<!--IF:MINDMAP-->[{{MINDMAP_B64}}]<!--/IF:MINDMAP-->ok", {"MINDMAP_B64": "x"}) == "[x]ok"
    assert R.expand("<!--IF:MINDMAP-->x<!--/IF:MINDMAP-->ok", {}) == "ok"


def test_expand_repeat_blocks():
    tpl = "<!--#CHAPTER--><h2>{{CHAPTER_TITLE}}</h2><!--#ENTRY--><b>{{SPEAKER}}</b>{{IDX}}<!--/ENTRY--><!--/CHAPTER-->"
    ctx = {"chapters": [{"title": "C1", "time": "", "entries": [
        {"speaker": "甲", "ts": "00:00:01", "paras": ["p1"], "color": "#111", "avatar": "甲", "idx": 1},
        {"speaker": "乙", "ts": "00:00:02", "paras": ["p2"], "color": "#222", "avatar": "乙", "idx": 2}]}]}
    assert R.expand(tpl, ctx) == "<h2>C1</h2><b>甲</b>1<b>乙</b>2"


def test_expand_missing_key_raises():
    try:
        R.expand("{{NOPE}}", {})
        assert False, "should raise SystemExit"
    except SystemExit:
        pass


def test_avatar_and_colors():
    assert R.avatar_char("demo 张三") == "张"
    assert R.avatar_char("赵六") == "赵"
    colors = R.assign_colors(["a", "b"], {})
    assert set(colors) == {"a", "b"} and all(v.startswith("#") for v in colors.values())
    preset = {"a": "#123456"}
    assert R.assign_colors(["a", "b"], preset)["a"] == "#123456"


def test_doctor_render_key_contract_sync():
    import doctor
    ctx_keys = {"TITLE", "KICKER", "DATE", "DURATION", "SPEAKERS_LINE", "SOURCE_URL", "MINDMAP_B64", "BODY"}
    block_keys = {"CHAPTER_TITLE", "CHAPTER_TIME", "SPEAKER", "COLOR", "AVATAR", "TS", "PARAS_HTML", "IDX"}
    assert doctor.KNOWN_KEYS == ctx_keys | block_keys


def test_render_doc_end_to_end():
    out = R.render_doc((FIX / "summary.md").read_text(encoding="utf-8"),
                       "tpl {{BODY}}", title="T", kicker="K", date="D", duration="1:00",
                       speakers_line="S", source_url="U", mindmap_png=None)
    assert "{{" not in out and "IF:MINDMAP" not in out and "<h2" in out


def test_render_minutes_requires_chapter_block():
    try:
        R.render_minutes((FIX / "minutes_polished.md").read_text(encoding="utf-8"),
                         "no chapter block here")
        assert False, "should raise SystemExit"
    except SystemExit:
        pass


def test_render_minutes_requires_entries():
    tpl = "<!--#CHAPTER--><!--#ENTRY-->{{SPEAKER}}<!--/ENTRY--><!--/CHAPTER-->"
    try:
        R.render_minutes("# 空文档\n\n这里没有任何发言块\n", tpl)
        assert False, "should raise SystemExit"
    except SystemExit:
        pass


def test_render_doc_requires_body():
    try:
        R.render_doc((FIX / "summary.md").read_text(encoding="utf-8"), "tpl")
        assert False, "should raise SystemExit"
    except SystemExit:
        pass


def test_split_chapter_paren_fallbacks():
    assert R._split_chapter("四、展望（2026）") == ("四、展望（2026）", "")
    assert R._split_chapter("三、业务介绍（重要）") == ("三、业务介绍（重要）", "")
    assert R._split_chapter("一、开场（00:00 – 00:03）") == ("一、开场", "00:00 – 00:03")


def test_entry_single_pass_no_injection():
    tpl = "<!--#CHAPTER--><!--#ENTRY-->{{SPEAKER}}|{{TS}}<!--/ENTRY--><!--/CHAPTER-->"
    ctx = {"chapters": [{"title": "C", "time": "", "entries": [
        {"speaker": "{{TS}}", "ts": "00:00:01", "paras": [], "color": "#111", "avatar": "x", "idx": 1}]}]}
    assert R.expand(tpl, ctx) == "{{TS}}|00:00:01"


def test_assign_colors_skips_preset():
    colors = R.assign_colors(["a", "b"], {"a": "#2563EB"})
    assert colors["a"] == "#2563EB" and colors["b"] == "#7C3AED"


def test_mindmap_requires_template_hook():
    tpl_min = "<!--#CHAPTER--><h2>{{CHAPTER_TITLE}}</h2><!--#ENTRY-->{{SPEAKER}} {{TS}}<!--/ENTRY--><!--/CHAPTER-->"
    try:
        R.render_minutes((FIX / "minutes_polished.md").read_text(encoding="utf-8"), tpl_min,
                         mindmap_png=b"\x89PNG")
        assert False, "render_minutes should raise SystemExit"
    except SystemExit:
        pass
    try:
        R.render_doc("# 标题\n\n正文", "tpl {{BODY}}", mindmap_png=b"\x89PNG")
        assert False, "render_doc should raise SystemExit"
    except SystemExit:
        pass
