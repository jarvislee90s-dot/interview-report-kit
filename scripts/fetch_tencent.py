# -*- coding: utf-8 -*-
"""fetch_tencent.py —— 腾讯会议录制分享页 URL → minutes_raw.json（带发言人、毫秒时间戳、段落文本）。
用法：python scripts/fetch_tencent.py "<https://meeting.tencent.com/cw/<code>>" [--auth-dir .auth]
       [--out minutes_raw.json] [--no-ai-summary]
公开分享链接无需登录；带访问密码/要求登录时弹浏览器等待（上限 600 秒）。可选抓腾讯 AI 纪要存
tencent_ai_summary.json（仅作 ⑥ 参考）。失败时按 reference/tencent-api.md 用 agent 浏览器手动兜底。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from speaker_check import warn_if_no_speakers

MINUTES_URL_HINT = "wemeet-cloudrecording-webapi/v1/minutes/detail"
SUMMARY_URL_HINT = "meetlog/public/record-detail/query-summary-and-note"

# 页面上下文分页拉逐字稿原始响应（字段映射在 Python 纯函数 paras_from_pages，便于单测）。
# 每页重生成 c_timestamp/c_nonce/rnds（实测每请求独立）；首页 start_pid=0，后续 pid=<上一页末段 pid>。
FETCH_JS = r"""
async ({path, tpl}) => {
  const rnd = () => Math.random().toString(36).slice(2, 10);
  const grab = async (q) => {
    q.set('c_timestamp', String(Date.now()));
    q.set('c_nonce', rnd()); q.set('rnds', rnd());
    const r = await fetch(location.origin + path + '?' + q.toString(), { credentials: 'include' });
    return await r.json();
  };
  const pages = [];
  let lastPid = null, more = true, guard = 0;
  while (more && guard++ < 2000) {
    const q = new URLSearchParams(tpl);
    if (lastPid != null) { q.delete('start_pid'); q.set('pid', String(lastPid)); }
    const j = await grab(q);
    if (!j || j.code !== 0 || !j.minutes) throw new Error('minutes/detail 异常 code=' + (j && j.code));
    pages.push(j);
    for (const p of (j.minutes.paragraphs || [])) if (p.pid != null) lastPid = p.pid;
    more = (j.more === true);
  }
  let title = '', meetingTime = '';
  try { title = document.title || ''; } catch (e) {}
  try {
    const m = (document.body.innerText || '').match(/\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}/);
    if (m) meetingTime = m[0].replace(/\//g, '-');
  } catch (e) {}
  return { pages, title, meetingTime };
}
"""


def paras_from_pages(pages: list) -> list:
    """minutes/detail 响应页列表 → paras[{s,t,x}]：s=speaker.user_name，t=start_time(毫秒)，
    x=sentences[].words[].text 顺序连接；空文本段过滤；按 t 升序。"""
    paras = []
    for pg in pages:
        for p in (pg.get("minutes", {}).get("paragraphs") or []):
            text = "".join(w.get("text", "") for s in (p.get("sentences") or [])
                           for w in (s.get("words") or []))
            if not text.strip():
                continue
            spk = p.get("speaker") or {}
            paras.append({"s": str(spk.get("user_name") or "").strip(),
                          "t": int(p.get("start_time") or 0), "x": text})
    paras.sort(key=lambda q: q["t"])
    return paras


def mmss(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


# 同步块：doctor.py / build_transcript.py / asr.py / fetch_feishu.py / apply_corrections.py / render.py 六个脚本的 GBK 容错保持一致
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        if _s and hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(errors="replace")
            except Exception:
                pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="腾讯会议录制分享 URL（https://meeting.tencent.com/cw/<code>）")
    ap.add_argument("--auth-dir", type=Path,
                    default=Path(__file__).resolve().parent.parent / ".auth",
                    help="浏览器登录态目录（与 fetch_feishu 共用，默认 skill 根下 .auth）")
    ap.add_argument("--out", type=Path, default=Path("minutes_raw.json"))
    ap.add_argument("--ai-summary-out", type=Path, default=Path("tencent_ai_summary.json"))
    ap.add_argument("--no-ai-summary", action="store_true", help="不抓腾讯 AI 纪要")
    a = ap.parse_args()
    if not re.search(r"meeting\.tencent\.com/cw/", a.url):
        sys.exit(f"URL 需形如 https://meeting.tencent.com/cw/<code>：{a.url}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("未安装 playwright：pip install playwright && playwright install chromium")

    a.auth_dir.mkdir(parents=True, exist_ok=True)
    ai_summary = {}
    data = None
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(a.auth_dir), headless=False,
                                                   viewport={"width": 1280, "height": 900})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if not a.no_ai_summary:
                def _on_resp(resp):
                    if SUMMARY_URL_HINT in resp.url and "body" not in ai_summary:
                        try:
                            ai_summary["body"] = resp.json()
                        except Exception:
                            pass
                page.on("response", _on_resp)
            captured = {}

            def _on_req(req):
                if MINUTES_URL_HINT in req.url and "query" not in captured:
                    captured["query"] = req.url
            page.on("request", _on_req)
            print(f"打开录制分享页：{a.url}")
            print("⏳ 若弹出密码/登录页请在浏览器中完成（等待上限 600 秒）…")
            page.goto(a.url, wait_until="domcontentloaded", timeout=60000)
            end = time.monotonic() + 600
            while "query" not in captured and time.monotonic() < end:
                page.wait_for_timeout(1000)
            if "query" not in captured:
                sys.exit("未捕获到逐字稿接口请求（600 秒）。页面可能要求登录/密码或接口已变化——"
                         "请按 reference/tencent-api.md 用 agent 浏览器手动兜底")
            sp = urlsplit(captured["query"])
            tpl = dict(parse_qsl(sp.query))
            tpl.pop("pid", None)
            tpl["start_pid"] = "0"
            print("📥 页面就绪，分页抓取逐字稿全文 …")
            data = page.evaluate(FETCH_JS, {"path": sp.path, "tpl": tpl})
        finally:
            ctx.close()

    paras = paras_from_pages((data or {}).get("pages") or [])
    if not paras:
        sys.exit("未抓到任何段落，接口疑似变化。请按 reference/tencent-api.md 用 agent 浏览器手动兜底")
    warn_if_no_speakers(paras)
    out_json = {"url": a.url, "title": (data or {}).get("title") or "",
                "meeting_time": (data or {}).get("meeting_time") or "",
                "source_label": "腾讯会议录制", "paras": paras}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out_json, ensure_ascii=False, indent=1), encoding="utf-8")
    if ai_summary.get("body") is not None:
        a.ai_summary_out.write_text(json.dumps(ai_summary["body"], ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        print(f"✅ 腾讯 AI 纪要已存：{a.ai_summary_out}（仅作 ⑥ 环节参考）")
    speakers = list(dict.fromkeys(q["s"] for q in paras if q["s"]))
    print(f"✅ 抓取完成：{len(paras)} 段 / {len(speakers)} 人 / 末段 {mmss(paras[-1]['t'])} → {a.out}")