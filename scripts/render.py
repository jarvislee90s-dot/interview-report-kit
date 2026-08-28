# -*- coding: utf-8 -*-
"""render.py —— markdown + 自包含模板 → HTML。独立 CLI，可脱离流水线单独套壳。
用法：
  python scripts/render.py <md> --template research-report/minutes  [--mindmap x.png] [--out y.html]
  python scripts/render.py --list-templates
模板：reference/templates/<set>/<doc>.html（doc ∈ minutes|summary）。
doc=minutes 需含 <!--#CHAPTER-->/<!--#ENTRY--> 可重复块；doc=summary 只需 {{BODY}}。
"""
import argparse
import base64
import html as html_mod
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TPL_DIR = SKILL_ROOT / "reference" / "templates"
PALETTE = ["#2563EB", "#7C3AED", "#0D9488", "#D97706", "#DC2626", "#DB2777",
           "#059669", "#EA580C", "#4F46E5", "#0891B2", "#65A30D", "#9333EA",
           "#0284C7", "#BE185D", "#4D7C0F", "#C2410C"]

META_RE = re.compile(r"^> (来源|会议时间|发言人|记录来源)：(.+)$", re.M)
ENTRY_RE = re.compile(r"^\*\*(.+?)\*\* ([\d: /–\-—]+)$")
CH_TIME_RE = re.compile(r"^(.+?)[（(]([\d:][\d: /–\-—]*)[)）]\s*$")
KEY_RE = re.compile(r"\{\{(\w+)\}\}")
ENTRY_KEY_RE = re.compile(r"\{\{(SPEAKER|TS|COLOR|AVATAR|IDX|PARAS_HTML)\}\}")
CHAPTER_KEY_RE = re.compile(r"\{\{(CHAPTER_TITLE|CHAPTER_TIME)\}\}")
IF_MINDMAP_RE = re.compile(r"<!--IF:MINDMAP-->(.*?)<!--/IF:MINDMAP-->", re.S)
CHAPTER_RE = re.compile(r"<!--#CHAPTER-->(.*?)<!--/CHAPTER-->", re.S)
ENTRY_BLOCK_RE = re.compile(r"<!--#ENTRY-->(.*?)<!--/ENTRY-->", re.S)
BLOCK_KEYS = {"CHAPTER_TITLE", "CHAPTER_TIME", "SPEAKER", "TS", "COLOR", "AVATAR", "IDX", "PARAS_HTML"}
COLORS_RE = re.compile(r"<!--COLORS:\s*(.*?)-->", re.S)
COLOR_PAIR_RE = re.compile(r"([\w\s\u4e00-\u9fff]+?)=#([0-9A-Fa-f]{6})")


def md_inline(s: str) -> str:
    """行内 md → HTML：先整体 escape，再 **x** → <strong>x</strong>。"""
    s = html_mod.escape(s, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def avatar_char(name: str) -> str:
    """头像字：剥离英文品牌前缀（如 demo/OceanDemo 及其后空白）后取首字符；空则回退原名首字符。"""
    token = name.strip()
    m = re.match(r"^[A-Za-z][A-Za-z0-9_-]*\s*", token)
    if m and token[m.end():]:
        token = token[m.end():]
    return (token or name)[0]


def _meta_of(src: str) -> dict:
    return {k: v.strip() for k, v in META_RE.findall(src)}


def _split_chapter(heading: str):
    """'一、开场（00:00 – 00:03）' → ('一、开场', '00:00 – 00:03')；括号内非时间范围
    （不含冒号，如（2026）/（重要））不当年份/徽标，整体作标题、time 为空。"""
    m = CH_TIME_RE.match(heading.strip())
    if m and ":" in m.group(2):
        return m.group(1).strip(), m.group(2).strip()
    return heading.strip(), ""


def parse_minutes_md(src: str) -> dict:
    """实录 md → {meta, chapters:[{title, time, entries:[{speaker, ts, paras}]}]}。
    正文取首个 \\n---\\n 之后；`## 标题（时间）` 开新章节；`**发言人** 时间` 开新时间块；
    其余非空行归入当前块 paras；无章节时自动归入唯一章节“发言记录”。头部区域忽略。
    """
    body = src.split("\n---\n", 1)
    body = body[1] if len(body) > 1 else src
    chapters, cur_ch, cur_entry = [], None, None
    for line in body.splitlines():
        line = line.rstrip()
        if line.startswith("## "):
            title, time_ = _split_chapter(line[3:])
            cur_ch = {"title": title, "time": time_, "entries": []}
            chapters.append(cur_ch)
            cur_entry = None
            continue
        em = ENTRY_RE.match(line)
        if em:
            if cur_ch is None:  # 无章节裸格式 → 唯一章节兜底
                cur_ch = {"title": "发言记录", "time": "", "entries": []}
                chapters.append(cur_ch)
            cur_entry = {"speaker": em.group(1).strip(), "ts": em.group(2).strip(), "paras": []}
            cur_ch["entries"].append(cur_entry)
            continue
        if line.strip() and cur_entry is not None:
            cur_entry["paras"].append(line.strip())
    return {"meta": _meta_of(src), "chapters": chapters}


def parse_doc_md(src: str) -> str:
    """极简 md → HTML：h1/h2/hr/ul/blockquote/p + 行内加粗。供 summary 模板 {{BODY}}。"""
    out, para, ul, bq = [], [], [], []

    def flush():
        nonlocal para, ul, bq
        if para:
            out.append("<p>" + "<br>\n".join(md_inline(x) for x in para) + "</p>")
        if ul:
            out.append("<ul>\n" + "\n".join(f"<li>{md_inline(x)}</li>" for x in ul) + "\n</ul>")
        if bq:
            out.append("<blockquote>\n" + "\n".join(f"<p>{md_inline(x)}</p>" for x in bq) + "\n</blockquote>")
        para, ul, bq = [], [], []

    for raw in src.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("## "):
            flush()
            out.append(f"<h2>{md_inline(line[3:].strip())}</h2>")
        elif line.startswith("# "):
            flush()
            out.append(f"<h1>{md_inline(line[2:].strip())}</h1>")
        elif re.fullmatch(r"-{3,}|\*{3,}", line):
            flush()
            out.append("<hr>")
        elif line.startswith("- "):
            if para or bq:
                flush()
            ul.append(line[2:].strip())
        elif line.startswith(">"):
            if para or ul:
                flush()
            bq.append(line.lstrip("> ").strip())
        else:
            if ul or bq:
                flush()
            para.append(line)
    flush()
    return "\n".join(out)


def _expand_entry(skel: str, e: dict) -> str:
    """单遍 re.sub 展开 entry 键：值里含 {{TS}} 等字面量也不会被二次替换（杜绝链式注入）。"""
    paras_html = e.get("paras_html") or "\n".join(f"<p>{md_inline(p)}</p>" for p in e.get("paras", []))
    raw = {"COLOR": str(e.get("color", "")), "AVATAR": str(e.get("avatar", "")),
           "IDX": str(e.get("idx", "")), "PARAS_HTML": paras_html}

    def _r(m):
        k = m.group(1)
        if k == "SPEAKER":
            return html_mod.escape(str(e.get("speaker", "")), quote=False)
        if k == "TS":
            return html_mod.escape(str(e.get("ts", "")), quote=False)
        return raw[k]

    return ENTRY_KEY_RE.sub(_r, skel)


def expand(tpl: str, ctx: dict) -> str:
    """占位符引擎：IF:MINDMAP 条件块 → #CHAPTER/#ENTRY 可重复块 → 单值 {{KEY}}。
    值替换前对模板预扫一次：ctx 键 ∪ 块内键之外的 {{KEY}} 视为模板错误并列出；
    替换后不回扫输出（避免正文值里的字面量被误报/二次注入）。
    """
    # 1) 条件块：有 MINDMAP_B64 保留内容（剥标记），否则整块删除
    tpl = IF_MINDMAP_RE.sub(lambda m: m.group(1) if ctx.get("MINDMAP_B64") else "", tpl)

    # 2) 预扫未知占位符（IF 剥离后、任何值替换前）
    unknown = sorted({k for k in KEY_RE.findall(tpl) if k not in set(ctx) | BLOCK_KEYS})
    if unknown:
        sys.exit(f"❌ 模板存在无法解析的占位符：{', '.join(unknown)}")

    # 3) 可重复块：#CHAPTER 内嵌 #ENTRY，按 ctx["chapters"] 逐章展开（单遍替换防注入）
    if "chapters" in ctx:
        def _chapter_block(m):
            inner = m.group(1)
            parts = []
            for ch in ctx["chapters"]:
                seg = inner
                em = ENTRY_BLOCK_RE.search(seg)
                if em:
                    rendered = "".join(_expand_entry(em.group(1), e) for e in ch.get("entries", []))
                    seg = seg[:em.start()] + rendered + seg[em.end():]
                fields = {"CHAPTER_TITLE": ch.get("title", ""), "CHAPTER_TIME": ch.get("time", "")}
                seg = CHAPTER_KEY_RE.sub(
                    lambda m2: html_mod.escape(str(fields[m2.group(1)]), quote=False), seg)
                parts.append(seg)
            return "".join(parts)

        tpl = CHAPTER_RE.sub(_chapter_block, tpl)

    # 4) 单值替换（re.sub 单遍：注入的值不会再被匹配）
    def _single(m):
        v = ctx.get(m.group(1))
        return m.group(0) if not isinstance(v, str) else v

    return KEY_RE.sub(_single, tpl)


def assign_colors(speakers: list, preset: dict) -> dict:
    """按出现顺序分配颜色：preset 优先，其余从 PALETTE 依次取未被 preset/已分配占用的色。"""
    out, used, n_auto = {}, set(preset.values()), 0
    for s in speakers:
        if s in preset:
            out[s] = preset[s]
            continue
        for c in PALETTE:
            if c not in used:
                out[s] = c
                used.add(c)
                break
        else:  # PALETTE 耗尽（发言人超过 16 色）时退回轮转
            out[s] = PALETTE[n_auto % len(PALETTE)]
        n_auto += 1
    return out


def _colors_comment(tpl: str) -> dict:
    """解析模板 `<!--COLORS: 名=#hex,…-->` 预置发言人配色。"""
    preset = {}
    m = COLORS_RE.search(tpl)
    if m:
        for name, hexv in COLOR_PAIR_RE.findall(m.group(1)):
            preset[name.strip()] = "#" + hexv
    return preset


def _strip_colors(tpl: str) -> str:
    return COLORS_RE.sub("", tpl)


def _head_ctx(md_text: str, **head) -> dict:
    """头部单值上下文：显式参数优先，缺省回退 md 元信息；SOURCE_URL 提取纯 URL
    （提不到用整行）；全部 html escape（quote=True）后返回。"""
    meta = _meta_of(md_text)
    parts = [p.strip() for p in meta.get("会议时间", "").split("·") if p.strip()]
    duration = next((p[len("时长"):].strip() for p in parts if p.startswith("时长")), "")
    h1 = re.search(r"^# (.+)$", md_text, re.M)
    src = head.get("source_url") or meta.get("来源", "") or meta.get("记录来源", "")
    um = re.search(r"https?://\S+", src)
    if um:
        src = um.group(0)
    png = head.get("mindmap_png")
    ctx = {
        "TITLE": head.get("title") or (h1.group(1).strip() if h1 else "会议纪要"),
        "KICKER": head.get("kicker") or "MEETING MINUTES",
        "DATE": head.get("date") or (parts[0] if parts else ""),
        "DURATION": head.get("duration") or duration,
        "SPEAKERS_LINE": head.get("speakers_line") or meta.get("发言人", ""),
        "SOURCE_URL": src,
        "MINDMAP_B64": base64.b64encode(png).decode("ascii") if png else "",
    }
    return {k: html_mod.escape(str(v), quote=True) for k, v in ctx.items()}


def _guard_mindmap(tpl: str, png) -> None:
    """导图承接守卫：模板既无 {{MINDMAP_B64}} 也无 IF:MINDMAP 块时，--mindmap 会被静默丢弃——响亮失败。"""
    if png is not None and "{{MINDMAP_B64}}" not in tpl and "<!--IF:MINDMAP-->" not in tpl:
        sys.exit("❌ 该模板不含导图承接块（IF:MINDMAP），无法嵌入 --mindmap；导图请配 summary 版式使用")


def render_minutes(md_text: str, tpl: str, title=None, kicker=None, date=None, duration=None,
                   speakers_line=None, source_url=None, mindmap_png=None) -> str:
    """实录模板渲染：解析 → 配色/头像/序号 → 头部 ctx + chapters → expand。"""
    _guard_mindmap(tpl, mindmap_png)
    preset = _colors_comment(tpl)
    tpl = _strip_colors(tpl)
    if not CHAPTER_RE.search(tpl):
        sys.exit("❌ minutes 模板必须包含 <!--#CHAPTER-->…<!--/CHAPTER--> 可重复块")
    data = parse_minutes_md(md_text)
    if not any(c["entries"] for c in data["chapters"]):
        sys.exit("❌ 未解析到任何发言块（**发言人** 时间）：输入 md 是否为纪要格式？")
    chapters = data["chapters"]
    speakers = []
    for c in chapters:
        for e in c["entries"]:
            if e["speaker"] not in speakers:
                speakers.append(e["speaker"])
    colors = assign_colors(speakers, preset)
    idx = 0
    for c in chapters:
        for e in c["entries"]:
            idx += 1
            e["color"] = colors[e["speaker"]]
            e["avatar"] = avatar_char(e["speaker"])
            e["idx"] = idx
            e["paras_html"] = "\n".join(f"<p>{md_inline(p)}</p>" for p in e["paras"])
    if not speakers_line:
        speakers_line = "、".join(speakers)
    ctx = _head_ctx(md_text, title=title, kicker=kicker, date=date, duration=duration,
                    speakers_line=speakers_line, source_url=source_url, mindmap_png=mindmap_png)
    ctx["chapters"] = chapters
    return expand(tpl, ctx)


def render_doc(md_text: str, tpl: str, title=None, kicker=None, date=None, duration=None,
               speakers_line=None, source_url=None, mindmap_png=None) -> str:
    """总结模板渲染：{{BODY}} = parse_doc_md(md_text)；模板缺 {{BODY}} 视为错误。"""
    _guard_mindmap(tpl, mindmap_png)
    tpl = _strip_colors(tpl)
    if "{{BODY}}" not in tpl:
        sys.exit("❌ summary 模板必须包含 {{BODY}} 占位符")
    # summary 缺省 kicker 与 minutes 区分（_head_ctx 通用缺省 "MEETING MINUTES" 仅供 minutes）
    ctx = _head_ctx(md_text, title=title, kicker=kicker or "MEETING SUMMARY", date=date,
                    duration=duration, speakers_line=speakers_line, source_url=source_url,
                    mindmap_png=mindmap_png)
    ctx["BODY"] = parse_doc_md(md_text)
    return expand(tpl, ctx)


# 同步块：doctor.py / build_transcript.py / asr.py / fetch_minutes.py / apply_corrections.py / render.py 六个脚本的 GBK 容错保持一致
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        if _s and hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(errors="replace")
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser(description="markdown + 模板 → HTML 渲染器")
    ap.add_argument("md", nargs="?", type=Path, help="输入 markdown（minutes 或 summary）")
    ap.add_argument("--template", help="模板 <set>/<doc>，doc ∈ minutes|summary")
    ap.add_argument("--mindmap", type=Path, help="思维导图 png（base64 内嵌，触发 IF:MINDMAP）")
    ap.add_argument("--out", type=Path, help="输出 html，缺省 <md>.html")
    ap.add_argument("--title")
    ap.add_argument("--kicker")
    ap.add_argument("--source-url", dest="source_url")
    ap.add_argument("--list-templates", action="store_true", help="列出可用模板")
    a = ap.parse_args()

    if a.list_templates:
        for p in sorted(TPL_DIR.glob("*/*.html")):
            print(f"{p.parent.name}: {p.stem}")
        return
    if not a.md or not a.template:
        sys.exit("用法：python scripts/render.py <md> --template <set>/<doc>（--list-templates 查看可用模板）")
    tpl_path = TPL_DIR / f"{a.template}.html"
    if not tpl_path.exists():
        avail = ", ".join(f"{p.parent.name}/{p.stem}" for p in sorted(TPL_DIR.glob("*/*.html")))
        hint = f"（可用模板：{avail}）" if avail else "（暂无可用模板，--list-templates 查看）"
        sys.exit(f"❌ 模板不存在：{tpl_path}{hint}")
    if not a.md.exists():
        sys.exit(f"❌ 输入文件不存在：{a.md}")
    if a.mindmap and not a.mindmap.exists():
        sys.exit(f"❌ 思维导图文件不存在：{a.mindmap}")

    tpl = tpl_path.read_text(encoding="utf-8")
    md_text = a.md.read_text(encoding="utf-8")
    png = a.mindmap.read_bytes() if a.mindmap else None
    if a.mindmap and ("{{MINDMAP_B64}}" not in tpl and "<!--IF:MINDMAP-->" not in tpl):
        sys.exit("❌ 该模板不含导图承接块（IF:MINDMAP），无法嵌入 --mindmap；导图请配 summary 版式使用")
    head = dict(title=a.title, kicker=a.kicker, source_url=a.source_url, mindmap_png=png)
    if a.template.rsplit("/", 1)[-1] == "minutes":
        out_html = render_minutes(md_text, tpl, **head)
    else:
        out_html = render_doc(md_text, tpl, **head)

    out = a.out or a.md.with_suffix(".html")
    if out.resolve() == a.md.resolve():
        sys.exit(f"❌ 输出与输入为同一文件，不允许覆盖源 md：{out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(out_html, encoding="utf-8")
    print(f"✅ {a.template} ← {a.md.name} → {out}（{out.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
