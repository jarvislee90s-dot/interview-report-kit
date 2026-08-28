# -*- coding: utf-8 -*-
"""fetch_feishu.py —— 飞书妙记 URL → minutes_raw.json（带发言人、毫秒时间戳、段落文本）。
用法：python scripts/fetch_feishu.py <妙记URL> [--auth-dir .auth] [--out minutes_raw.json]
首次运行弹出浏览器扫码登录；登录态持久保存于 --auth-dir，之后免登。
失败时按 reference/feishu-api.md 用 agent 浏览器手动兜底。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

# 在妙记页面上下文内执行：同源带 cookie 调妙记 web 接口，拼出 {s,t,x} 段落数组。
# 字段路径为 2026-08-27 实测：paragraph-ids→data.list[].pid/start_time、
# speakers→data.speaker_info_map{}.user_name + paragraph_to_speaker{pid→uid}、
# subtitles_v2→data.paragraphs[].pid/start_time/sentences[].contents[].content、
# clip→data.start_time 等毫秒字段。任一接口缺失即抛错，由 Python 侧走手册兜底。
FETCH_JS = r"""
async ({token, pageUrl}) => {
  const base = `https://${location.hostname}`;
  const SIZE = 150;  // 每页段数：URL size 与短页判断共用
  const get = async (u) => (await fetch(u, { credentials: 'include' })).json();
  const sp = await get(`${base}/minutes/api/speakers?size=10000&translate_lang=default&object_token=${token}&language=zh_cn`);
  const pids = await get(`${base}/minutes/api/subtitles/paragraph-ids?page_size=10000&page_num=0&object_token=${token}&language=zh_cn`);
  const idList = pids.data.list;
  const total = idList.length;
  const nameOf = {};
  for (const [uid, info] of Object.entries(sp.data.speaker_info_map || {})) nameOf[uid] = info.user_name;
  const p2s = sp.data.paragraph_to_speaker || {};
  const paras = [];
  const gotPids = new Set();  // 已抓段落 pid 集合，“下一段”按 pid 匹配（比 start_time 稳）
  let cursorPid = idList[0].pid, guard = 0;
  while (paras.length < total && guard++ < Math.ceil(total / SIZE) + 5) {
    const sub = await get(`${base}/minutes/api/subtitles_v2?paragraph_id=${cursorPid}&size=${SIZE}&translate_lang=default&is_fluent=false&filter_speaker=true&object_token=${token}&language=zh_cn`);
    const list = sub.data.paragraphs || [];
    if (!list.length) break;
    for (const p of list) {
      let text = '';
      for (const sent of (p.sentences || [])) for (const c of (sent.contents || [])) text += (c.content || '');
      gotPids.add(p.pid);
      paras.push({ s: nameOf[p2s[p.pid]] || '', t: Number(p.start_time), x: text });
    }
    if (list.length < SIZE) break;
    const next = idList.find(i => !gotPids.has(i.pid));
    if (!next) break;
    cursorPid = next.pid;
  }
  paras.sort((a, b) => a.t - b.t);
  let meetingTime = '';
  try {
    const clip = await get(`${base}/minutes/api/clip?object_token=${token}&language=zh_cn`);
    const d = clip && clip.data ? clip.data : {};
    const ms = d.start_time || d.create_time || d.meeting_time || (d.meeting_info && d.meeting_info.start_time) || 0;
    if (ms) { const dt = new Date(Number(ms)); if (!isNaN(dt)) meetingTime = dt.toLocaleString('sv-SE', { hour12: false }).slice(0, 16).replace('T', ' '); }
  } catch (e) {}
  return { url: pageUrl, title: document.title, meeting_time: meetingTime, total_expected: total, paras };
}
"""


def token_of(url: str) -> str:
    m = re.search(r"/minutes/([A-Za-z0-9]+)", url)
    if not m:
        sys.exit(f"无法从 URL 解析妙记 token（需形如 https://xxx.feishu.cn/minutes/<token>）：{url}")
    return m.group(1)


def mmss(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def wait_off_accounts(page, prompt: bool = False) -> None:
    """等待离开飞书登录页（/accounts）。首次 goto 与 re-goto 后都可能遇到登录重定向，故复用。"""
    if prompt and "/accounts" in page.url:
        print("⏳ 请在弹出的浏览器中登录飞书…（登录态存于 .auth，之后免登；超时 600 秒）")
    deadline = time.monotonic() + 600
    while "/accounts" in page.url:
        if time.monotonic() > deadline:
            sys.exit("⏳ 等待登录超时（600 秒），请重跑并在弹出的浏览器内完成扫码")
        page.wait_for_timeout(2000)


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
    ap.add_argument("url", help="飞书妙记 URL（https://xxx.feishu.cn/minutes/<token>）")
    ap.add_argument("--auth-dir", type=Path,
                    default=Path(__file__).resolve().parent.parent / ".auth",
                    help="浏览器登录态目录（默认 skill 根下 .auth，持久免登）")
    ap.add_argument("--out", type=Path, default=Path("minutes_raw.json"))
    a = ap.parse_args()
    token = token_of(a.url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("未安装 playwright：pip install playwright && playwright install chromium")

    a.auth_dir.mkdir(parents=True, exist_ok=True)
    data = None
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(a.auth_dir), headless=False,
                                                   viewport={"width": 1280, "height": 900})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            print(f"打开妙记页面：{a.url}")
            page.goto(a.url, wait_until="domcontentloaded")
            wait_off_accounts(page, prompt=True)
            page.wait_for_timeout(5000)  # 等待应用引导完成
            if "/minutes" not in page.url:  # 登录后未自动跳回则重开一次（重开可能再触发 /accounts 重定向）
                page.goto(a.url, wait_until="domcontentloaded")
                wait_off_accounts(page)
                page.wait_for_timeout(3000)
            if "/minutes" not in page.url:
                sys.exit(f"未到达妙记页面（当前：{page.url}）。请按 reference/feishu-api.md 用 agent 浏览器手动兜底")
            print("📥 页面就绪，调用妙记接口抓取全文 …")
            try:  # 接口路径/字段变化时 evaluate 内抛错（如 data.list 缺失），走手册兜底
                data = page.evaluate(FETCH_JS, {"token": token, "pageUrl": a.url})
            except Exception as e:
                sys.exit(f"页面上下文抓取失败（{type(e).__name__}: {e}）。请按 reference/feishu-api.md 用 agent 浏览器手动兜底")
        finally:
            ctx.close()

    if not isinstance(data, dict):
        sys.exit("页面上下文抓取返回异常结果。请按 reference/feishu-api.md 用 agent 浏览器手动兜底")
    paras = data.get("paras") or []
    total = int(data.get("total_expected") or 0)
    if not paras:
        sys.exit("未抓到任何段落，接口疑似变化。请按 reference/feishu-api.md 用 agent 浏览器手动兜底")
    if total and len(paras) < total * 0.9:
        sys.exit(f"❌ 抓取不完整：{len(paras)}/{total} 段（不足 90%），接口疑似变化。"
                 "请按 reference/feishu-api.md 用 agent 浏览器手动兜底")
    speakers = list(dict.fromkeys(q.get("s") for q in paras if q.get("s")))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    last_ms = max((int(q.get("t", 0)) for q in paras), default=0)
    print(f"✅ 抓取完成：{len(paras)} 段 / {len(speakers)} 人 / 末段 {mmss(last_ms)} → {a.out}")
