# interview-report-kit 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建造完全自包含的 `interview-report-kit` skill：妙记爬取→ASR→校正→润色→总结→导图→模板化 HTML 渲染的全流程工具集，5 套模板 set，他人拷走文件夹即用。

**Architecture:** 6 个独立 CLI 脚本（各管一个环节）+ 自包含模板库（完整 HTML + 字符串占位符，结构在模板、数据由 render.py 注入）+ SKILL.md 工作流指引与 reference 手册。LLM 环节（校正规则/润色/总结/导图）由 agent 按 SKILL.md 执行，产物都是可编辑 markdown。

**Tech Stack:** Python 3.10+（playwright、faster-whisper）、ffmpeg、Node+mmdc、pytest。

**Spec:** `E:\LLMproject\PersonalAffairs\远洋示例\docs\superpowers\specs\2026-03-10-interview-report-kit-design.md`

**测试数据（本会话已产出，作为 E2E 夹具）：**
`D = E:\LLMproject\PersonalAffairs\远洋示例\20180827-OceanDemo路演访谈`
- `D\会议实录（修正）.md`（润色版格式：## 章节 + `**发言人** 时间` 块 + 段内加粗）
- `D\会议总结.md`、`D\会议总结思维导图.png`、`D\minutes_raw.json`、`D\会议实录.md`（原始格式）
- 本次两个最终 HTML（研报风纪要/简洁总结）作为模板抽取源

---

## File Structure（全部新建于 skill 根目录）

```
C:\Users\bunny\.agents\skills\interview-report-kit\
├── SKILL.md
├── requirements.txt
├── scripts\{doctor,fetch_minutes,build_transcript,asr,apply_corrections,render}.py
├── reference\templates\{research-report,clean-doc,modern-card,chat-bubble,timeline}\{minutes,summary}.html
├── reference\pipeline.md
├── reference\feishu-api.md
└── tests\test_render.py + fixtures\
```

任务顺序：0 脚手架 → 1 doctor → 2 build_transcript → 3 asr → 4 fetch_minutes → 5 apply_corrections → 6 render 核心（TDD）→ 7~11 五套模板 → 12 SKILL.md+reference → 13 E2E 终验。

---

### Task 0: 脚手架与 git 初始化

**Files:** Create 目录结构 + requirements.txt + .gitignore

- [ ] **Step 1: 创建目录**

```bash
mkdir -p "C:\Users\bunny\.agents\skills\interview-report-kit\scripts" \
         "C:\Users\bunny\.agents\skills\interview-report-kit\tests\fixtures" \
         "C:\Users\bunny\.agents\skills\interview-report-kit\reference\templates\research-report" \
         "C:\Users\bunny\.agents\skills\interview-report-kit\reference\templates\clean-doc" \
         "C:\Users\bunny\.agents\skills\interview-report-kit\reference\templates\modern-card" \
         "C:\Users\bunny\.agents\skills\interview-report-kit\reference\templates\chat-bubble" \
         "C:\Users\bunny\.agents\skills\interview-report-kit\reference\templates\timeline"
cd "C:\Users\bunny\.agents\skills\interview-report-kit" && git init
```

- [ ] **Step 2: 写 requirements.txt 与 .gitignore**

requirements.txt：
```
playwright>=1.40
faster-whisper>=1.0
pytest>=8.0
```

.gitignore：
```
.auth/
__pycache__/
*.pyc
runs/
```

- [ ] **Step 3: 复制测试夹具并提交**

```bash
cp "E:\LLMproject\PersonalAffairs\远洋示例\20180827-OceanDemo路演访谈\会议实录（修正）.md" tests\fixtures\minutes_polished.md
cp "E:\LLMproject\PersonalAffairs\远洋示例\20180827-OceanDemo路演访谈\会议实录.md" tests\fixtures\minutes_raw.md
cp "E:\LLMproject\PersonalAffairs\远洋示例\20180827-OceanDemo路演访谈\会议总结.md" tests\fixtures\summary.md
cp "E:\LLMproject\PersonalAffairs\远洋示例\20180827-OceanDemo路演访谈\minutes_raw.json" tests\fixtures\minutes_raw.json
git add -A && git commit -m "chore: scaffold interview-report-kit with test fixtures"
```

---

### Task 1: doctor.py（环境自检 + 模板校验）

**Files:** Create `scripts/doctor.py`

- [ ] **Step 1: 写实现**

```python
# -*- coding: utf-8 -*-
"""doctor.py —— 环境自检；--check-template 校验模板占位符。退出码 0=全部可用。"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
KNOWN_KEYS = {"TITLE", "KICKER", "DATE", "DURATION", "SPEAKERS_LINE", "SOURCE_URL",
              "MINDMAP_B64", "BODY", "CHAPTER_TITLE", "CHAPTER_TIME",
              "SPEAKER", "COLOR", "AVATAR", "TS", "PARAS_HTML", "IDX"}


def check_env() -> int:
    bad = 0

    def item(name: str, ok: bool, hint: str = ""):
        nonlocal bad
        print(("  ✅ " if ok else "  ❌ ") + name + (f"   {hint}" if not ok and hint else ""))
        if not ok:
            bad += 1

    print("🔍 interview-report-kit 环境自检")
    item("ffmpeg", shutil.which("ffmpeg") is not None, "安装：winget install Gyan.FFmpeg 或 brew install ffmpeg")
    item("node", shutil.which("node") is not None, "安装：https://nodejs.org")
    item("mmdc(mermaid-cli)", shutil.which("mmdc") is not None, "安装：npm i -g @mermaid-js/mermaid-cli")
    for mod, hint in (("playwright", "pip install playwright && playwright install chromium"),
                      ("faster_whisper", "pip install faster-whisper")):
        try:
            __import__(mod)
            item(f"python:{mod}", True)
        except ImportError:
            item(f"python:{mod}", False, hint)
    return 1 if bad else 0


def check_template(path: Path) -> int:
    txt = path.read_text(encoding="utf-8")
    problems = []
    for m in re.finditer(r"\{\{(\w+)\}\}", txt):
        if m.group(1) not in KNOWN_KEYS:
            problems.append(f"未知占位符 {{{{{m.group(1)}}}}}")
    for kind in ("IF:MINDMAP", "#CHAPTER", "#ENTRY"):
        if f"<!--{kind}-->" in txt and f"<!--/{kind.lstrip('#')}-->" not in txt:
            problems.append(f"块 <!--{kind}--> 未闭合")
    if "<!--#ENTRY-->" in txt and "<!--#CHAPTER-->" not in txt:
        problems.append("#ENTRY 块必须嵌套在 #CHAPTER 块内")
    for p in problems:
        print("  ❌ " + p)
    if not problems:
        print(f"  ✅ 模板合法：{path.name}")
    return 1 if problems else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--check-template":
        sys.exit(check_template(Path(args[1])))
    sys.exit(check_env())
```

- [ ] **Step 2: 运行验证**

Run: `cd "C:\Users\bunny\.agents\skills\interview-report-kit" && python scripts/doctor.py`
Expected: 本机应全 ✅（本会话已装齐 playwright 环境除外——若 playwright 缺失按提示装）。

- [ ] **Step 3: Commit**

```bash
git add scripts/doctor.py && git commit -m "feat: doctor env & template checker"
```

---

### Task 2: build_transcript.py（json→会议实录.md）

**Files:** Create `scripts/build_transcript.py`

- [ ] **Step 1: 写实现**

```python
# -*- coding: utf-8 -*-
"""build_transcript.py —— minutes_raw.json → 会议实录.md（逐段：**发言人** 时间戳 + 段落）。
用法：python scripts/build_transcript.py minutes_raw.json [--out 会议实录.md]
json 结构：{"total_expected":N,"paras":[{"s":发言人,"t":毫秒,"x":文本},...]}（fetch_minutes.py 产出）
"""
import argparse
import json
import sys
from pathlib import Path


def hmss(ms: int) -> str:
    s = ms // 1000
    return f"{s//3600:02d}:{s//60%60:02d}:{s%60:02d}"


def build(md_path: Path, json_path: Path) -> None:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    paras = raw["paras"]
    speakers = list(dict.fromkeys(p["s"] for p in paras if p["s"]))
    lines = [
        "# 访谈会议实录",
        "",
        "> 记录来源：飞书妙记（自动化爬取）",
        f"> 发言人 {len(speakers)} 人：{'、'.join(speakers)}",
        f"> 发言 {len(paras)} 段 · 末段 {hmss(paras[-1]['t']) if paras else '-'}",
        "> 说明：本文件为原始实录，未经校对。",
        "",
        "---",
        "",
    ]
    for p in paras:
        text = " ".join(str(p["x"]).split())
        if not text:
            continue
        lines += [f"**{p['s']}** {hmss(int(p['t']))}", "", text, ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {md_path}（{len(paras)} 段 / {len(speakers)} 人）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", type=Path)
    ap.add_argument("--out", type=Path, default=Path("会议实录.md"))
    a = ap.parse_args()
    if not a.json_path.exists():
        sys.exit(f"文件不存在：{a.json_path}")
    build(a.out, a.json_path)
```

- [ ] **Step 2: 用夹具验证**

Run: `cd "C:\Users\bunny\.agents\skills\interview-report-kit" && python scripts/build_transcript.py tests/fixtures/minutes_raw.json --out runs/_t.md`
Expected: 打印 `written: runs/_t.md（150 段 / 8 人）`；`grep -c '^\*\*' runs/_t.md` = 150。

- [ ] **Step 3: Commit**

```bash
git add scripts/build_transcript.py && git commit -m "feat: build_transcript json to md"
```

---

### Task 3: asr.py（自包含音频转录）

**Files:** Create `scripts/asr.py`

- [ ] **Step 1: 写实现**

```python
# -*- coding: utf-8 -*-
"""asr.py —— 音频文件 → transcript.txt / transcript.json（ffmpeg 提取 + faster-whisper）。
用法：python scripts/asr.py <音频/视频文件> [--model large-v3-turbo] [--language zh] [--outdir .]
说明：CPU 转录约 1.2× 音频时长；产物已存在则跳过（断点续跑）。HF 下载失败时自动切 hf-mirror。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def extract_wav(src: Path, wav: Path) -> None:
    if wav.exists():
        print(f"  ✅ 音频已存在：{wav}")
        return
    print("  🎵 ffmpeg 提取 16k 单声道 wav …")
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1", str(wav)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def transcribe(wav: Path, model: str, language: str, outdir: Path) -> None:
    txt, js = outdir / "transcript.txt", outdir / "transcript.json"
    if txt.exists() and js.exists():
        print("  ✅ 转录已存在，跳过")
        return
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("未安装 faster-whisper：pip install faster-whisper")
    wm = WhisperModel(model, device="auto", compute_type="auto")
    segments, info = wm.transcribe(str(wav), language=language, vad_filter=True)
    rows, lines = [], []
    for seg in segments:
        rows.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        lines.append(seg.text.strip())
        print(f"    [{seg.start:8.1f}] {seg.text.strip()[:40]}", end="\r")
    print()
    txt.write_text("\n".join(lines), encoding="utf-8")
    js.write_text(json.dumps({"language": info.language, "duration": info.duration,
                              "segments": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ✅ 转录完成：{len(rows)} 段 → {txt.name} / {js.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("media", type=Path)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--outdir", type=Path, default=Path("."))
    a = ap.parse_args()
    if not a.media.exists():
        sys.exit(f"文件不存在：{a.media}")
    a.outdir.mkdir(parents=True, exist_ok=True)
    wav = a.outdir / "audio.wav"
    extract_wav(a.media, wav)
    if not os.environ.get("HF_ENDPOINT"):
        try:
            transcribe(wav, a.model, a.language, a.outdir)
        except Exception as e:
            print(f"  ⚠️ 默认源失败（{type(e).__name__}），改用 hf-mirror 重试…")
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            transcribe(wav, a.model, a.language, a.outdir)
    else:
        transcribe(wav, a.model, a.language, a.outdir)
```

- [ ] **Step 2: 冒烟验证（只验 ffmpeg 分支与参数解析，完整转录不做——CPU 80 分钟）**

Run: `cd "C:\Users\bunny\.agents\skills\interview-report-kit" && python scripts/asr.py --help`
Expected: 打印用法无报错。

- [ ] **Step 3: Commit**

```bash
git add scripts/asr.py && git commit -m "feat: self-contained asr script"
```

---

### Task 4: fetch_minutes.py（妙记爬取，playwright 持久登录态）

**Files:** Create `scripts/fetch_minutes.py`

- [ ] **Step 1: 写实现**

```python
# -*- coding: utf-8 -*-
"""fetch_minutes.py —— 飞书妙记 URL → minutes_raw.json（带发言人、毫秒时间戳、段落文本）。
用法：python scripts/fetch_minutes.py <妙记URL> [--auth-dir .auth] [--out minutes_raw.json]
首次运行弹出浏览器扫码登录；登录态持久保存于 --auth-dir，之后免登。
失败时按 reference/feishu-api.md 用 agent 浏览器手动兜底。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

FETCH_JS = """
async (token) => {
  const base = `https://${location.hostname}`;
  const get = async (u) => (await fetch(u, { credentials: 'include' })).json();
  const sp = await get(`${base}/minutes/api/speakers?size=10000&translate_lang=default&object_token=${token}&language=zh_cn`);
  const pids = await get(`${base}/minutes/api/subtitles/paragraph-ids?page_size=10000&page_num=0&object_token=${token}&language=zh_cn`);
  const idList = pids.data.list;
  const total = idList.length;
  const nameOf = {};
  for (const [uid, info] of Object.entries(sp.data.speaker_info_map || {})) nameOf[uid] = info.user_name;
  const p2s = sp.data.paragraph_to_speaker || {};
  const paras = [];
  let cursorPid = idList[0].pid, guard = 0;
  while (paras.length < total && guard++ < 30) {
    const sub = await get(`${base}/minutes/api/subtitles_v2?paragraph_id=${cursorPid}&size=150&translate_lang=default&is_fluent=false&filter_speaker=true&object_token=${token}&language=zh_cn`);
    const list = sub.data.paragraphs || [];
    if (!list.length) break;
    for (const p of list) {
      let text = '';
      for (const sent of (p.sentences || [])) for (const c of (sent.contents || [])) text += (c.content || '');
      paras.push({ s: nameOf[p2s[p.pid]] || '', t: Number(p.start_time), x: text });
    }
    if (list.length < 150) break;
    const got = new Set(paras.map(p => p.t));
    const next = idList.find(i => !got.has(Number(i.start_time)));
    if (!next) break;
    cursorPid = next.pid;
  }
  paras.sort((a, b) => a.t - b.t);
  return { total_expected: total, paras };
}
"""


def token_of(url: str) -> str:
    m = re.search(r"/minutes/([A-Za-z0-9]+)", url)
    if not m:
        sys.exit("无法从 URL 解析 object_token（应为 …/minutes/<token>）")
    return m.group(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--auth-dir", type=Path, default=Path(__file__).resolve().parent.parent / ".auth")
    ap.add_argument("--out", type=Path, default=Path("minutes_raw.json"))
    a = ap.parse_args()
    token = token_of(a.url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("未安装 playwright：pip install playwright && playwright install chromium")

    a.auth_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(a.auth_dir), headless=False,
                                                    viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(a.url, wait_until="domcontentloaded")
        if "/accounts" in page.url:  # 未登录
            print("⏳ 请在弹出的浏览器中登录飞书（扫码/账密）。登录完成后自动继续…")
            deadline = time.time() + 600
            while "/accounts" in page.url and time.time() < deadline:
                page.wait_for_timeout(2000)
            if "/accounts" in page.url:
                ctx.close(); sys.exit("❌ 10 分钟未完成登录，退出")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(5000)  # 等妙记前端初始化
        if "/minutes" not in page.url:
            ctx.close(); sys.exit(f"❌ 页面异常：{page.url}（无权限？按 reference/feishu-api.md 手动兜底）")
        data = page.evaluate(FETCH_JS, token)
        ctx.close()
    paras = data["paras"]
    if len(paras) < data["total_expected"] * 0.9:
        sys.exit(f"❌ 仅取到 {len(paras)}/{data['total_expected']} 段，疑似接口变化，按 feishu-api.md 兜底")
    a.out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"✅ written: {a.out}（{len(paras)} 段 / {len(set(p['s'] for p in paras))} 人 / "
          f"末段 {paras[-1]['t']//1000//60}:{paras[-1]['t']//1000%60:02d}）")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 冒烟验证（URL 解析与参数）**

Run: `python scripts/fetch_minutes.py --help && python -c "import ast;ast.parse(open(r'scripts/fetch_minutes.py',encoding='utf-8').read())" && echo SYNTAX_OK`
Expected: 用法正常 + SYNTAX_OK。（真实爬取在 Task 13 用本次妙记 URL 实测——登录态已存于 .auth）

- [ ] **Step 3: Commit**

```bash
git add scripts/fetch_minutes.py && git commit -m "feat: feishu minutes crawler with persistent auth"
```

---

### Task 5: apply_corrections.py（校正执行器）

**Files:** Create `scripts/apply_corrections.py`

- [ ] **Step 1: 写实现**

```python
# -*- coding: utf-8 -*-
"""apply_corrections.py —— 读 corrections.json（agent 生成的校正规则）应用到 会议实录.md。
用法：python scripts/apply_corrections.py <会议实录.md> <corrections.json> [--out 会议实录（修正）.md]
规则格式：[{"old":"原文","new":"修正","expect":1,"basis":"依据"},...]
硬校验：每条规则命中数必须等于 expect；输出段落数必须与输入一致；违规即失败并报告。
"""
import argparse
import json
import re
import sys
from pathlib import Path

PAT = re.compile(r"\*\*(.+?)\*\* (\d{2}:\d{2}:\d{2})", re.M)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("rules", type=Path)
    ap.add_argument("--out", type=Path, default=Path("会议实录（修正）.md"))
    a = ap.parse_args()
    src = a.src.read_text(encoding="utf-8")
    rules = json.loads(a.rules.read_text(encoding="utf-8"))
    n_in = len(PAT.findall(src))
    misses, applied = [], 0
    for i, r in enumerate(rules, 1):
        n = src.count(r["old"])
        if n != r.get("expect", 1):
            misses.append(f"规则{i} 「{r['old'][:24]}」命中 {n} 次，预期 {r.get('expect', 1)}")
            continue
        src = src.replace(r["old"], r["new"])
        applied += 1
    n_out = len(PAT.findall(src))
    if misses:
        print("❌ 规则未命中（未写入，请修正规则后重跑）：")
        for m in misses:
            print("   -", m)
        sys.exit(1)
    if n_in != n_out:
        sys.exit(f"❌ 段落数变化：{n_in} → {n_out}（规则不得吞并段落标记）")
    header = src.split("\n---\n", 1)[0]
    header = header.replace("> 说明：本文件为原始实录，未经校对。",
                             "> 说明：本文件已对照本地音频转录逐段交叉校对（依据见 corrections.json）。")
    a.out.write_text(header + "\n---\n" + src.split("\n---\n", 1)[1], encoding="utf-8")
    print(f"✅ applied {applied}/{len(rules)} 条 → {a.out}（段落数 {n_out} 不变）")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 夹具验证**

```bash
cat > runs/_rules.json <<'EOF'
[{"old":"这个其实也是香港澳门中心的建设","new":"【测试】这个其实也是香港澳门中心的建设","expect":1,"basis":"test"}]
EOF
python scripts/apply_corrections.py tests/fixtures/minutes_raw.md runs/_rules.json --out runs/_t2.md
grep -c '^\*\*' runs/_t2.md
```
Expected: `✅ applied 1/1 条`；段落数 150。
再跑一条 expect=2 实际 1 的规则确认报错退出码 1。

- [ ] **Step 3: Commit**

```bash
git add scripts/apply_corrections.py && git commit -m "feat: corrections executor with hard validation"
```

---

### Task 6: render.py 核心（TDD）

**Files:** Create `scripts/render.py`、`tests/test_render.py`

- [ ] **Step 1: 写失败测试**

```python
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
    total = sum(len(c["entries"]) for c in ch)
    assert total == 53


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
    ctx = {"TITLE": "A", "MINDMAP_B64": "x"}
    assert R.expand("<t>{{TITLE}}</t>", ctx) == "<t>A</t>"
    out = R.expand("<!--IF:MINDMAP-->[{{MINDMAP_B64}}]<!--/IF:MINDMAP-->ok", ctx)
    assert out == "[x]ok"
    out2 = R.expand("<!--IF:MINDMAP-->x<!--/IF:MINDMAP-->ok", {})
    assert out2 == "ok"


def test_expand_repeat_blocks():
    tpl = "<!--#CHAPTER--><h2>{{CHAPTER_TITLE}}</h2><!--#ENTRY--><b>{{SPEAKER}}</b>{{IDX}}<!--/ENTRY--><!--/CHAPTER-->"
    ctx = {"chapters": [{"title": "C1", "time": "", "entries": [
        {"speaker": "甲", "ts": "00:00:01", "paras": ["p1"], "color": "#111", "avatar": "甲", "idx": 1},
        {"speaker": "乙", "ts": "00:00:02", "paras": ["p2"], "color": "#222", "avatar": "乙", "idx": 2}]}]}
    out = R.expand(tpl, ctx)
    assert out == "<h2>C1</h2><b>甲</b>1<b>乙</b>2"


def test_avatar_and_colors():
    assert R.avatar_char("demo 张三") == "李"
    assert R.avatar_char("赵六") == "张"
    colors = R.assign_colors(["a", "b"], {})
    assert set(colors) == {"a", "b"} and all(v.startswith("#") for v in colors.values())


def test_render_doc_end_to_end():
    out = R.render_doc((FIX / "summary.md").read_text(encoding="utf-8"),
                       "tpl", title="T", kicker="K", date="D", duration="1:00",
                       speakers_line="S", source_url="U", mindmap_png=None)
    assert "{{" not in out and "MINDMAP" not in out and "<h2" in out
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\bunny\.agents\skills\interview-report-kit" && python -m pytest tests/test_render.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'render'`）。

- [ ] **Step 3: 写 render.py 实现**

```python
# -*- coding: utf-8 -*-
"""render.py —— markdown + 自包含模板 → HTML。独立 CLI，可脱离流水线单独套壳。
用法：
  python scripts/render.py <md> --template research-report/minutes  [--mindmap x.png] [--out y.html]
  python scripts/render.py <md> --template clean-doc/summary --mindmap x.png
  python scripts/render.py --list-templates
模板：reference/templates/<set>/<doc>.html，占位符见 SKILL.md / doctor --check-template。
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


# ---------- markdown 解析 ----------
def md_inline(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_mod.escape(s, quote=False))


def avatar_char(name: str) -> str:
    token = name.replace("brand", "").replace("OceanDemo", "").strip()
    return (token or name)[0]


def _meta_of(src: str) -> dict:
    meta = {}
    for line in src.splitlines():
        m = re.match(r"^> (来源|会议时间|发言人|记录来源)：(.+)$", line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta


def parse_minutes_md(src: str) -> dict:
    meta = _meta_of(src)
    body = src.split("\n---\n", 1)[-1]
    chapters, cur, cur_ent = [], None, None
    for line in body.splitlines():
        t = line.strip()
        if t.startswith("## "):
            title = t[3:].strip()
            tm = re.search(r"（([\d: /–\-—]+)）", title)
            cur = {"title": re.sub(r"（[\d: /–\-—]+）", "", title).strip(),
                   "time": tm.group(1).strip() if tm else "", "entries": []}
            chapters.append(cur)
            cur_ent = None
            continue
        m = re.match(r"^\*\*(.+?)\*\* ([\d: /–\-—]+)$", t)
        if m and cur is not None:
            cur_ent = {"speaker": m.group(1).strip(), "ts": m.group(2).strip(), "paras": []}
            cur["entries"].append(cur_ent)
            continue
        if m:  # 无章节时的裸块
            cur = {"title": "发言记录", "time": "", "entries": []}
            chapters.append(cur)
            cur_ent = {"speaker": m.group(1).strip(), "ts": m.group(2).strip(), "paras": []}
            cur["entries"].append(cur_ent)
            continue
        if t and cur_ent is not None:
            cur_ent["paras"].append(t)
    return {"meta": meta, "chapters": chapters}


def parse_doc_md(src: str) -> str:
    """极简 md→HTML：h1/h2/hr/ul/blockquote/p/加粗。"""
    out, in_ul, bq = [], False, []

    def flush():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if bq:
            out.append("<blockquote>" + "<br>".join(bq) + "</blockquote>")
            bq.clear()

    for raw in src.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush(); continue
        if line.startswith("# "):
            flush(); out.append(f"<h1>{md_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            flush(); out.append(f"<h2>{md_inline(line[3:])}</h2>")
        elif line.strip() == "---":
            flush(); out.append("<hr>")
        elif line.startswith("- "):
            if bq:
                flush()
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{md_inline(line[2:])}</li>")
        elif line.startswith("> "):
            if in_ul:
                flush()
            bq.append(md_inline(line[2:]))
        else:
            flush(); out.append(f"<p>{md_inline(line)}</p>")
    flush()
    return "\n".join(out)


# ---------- 占位符引擎 ----------
def expand(tpl: str, ctx: dict) -> str:
    tpl = re.sub(r"<!--IF:MINDMAP-->.*?<!--/IF:MINDMAP-->",
                 (lambda m: m.group(0)) if ctx.get("MINDMAP_B64") else (lambda m: ""),
                 tpl, flags=re.S) if not ctx.get("MINDMAP_B64") else tpl
    if ctx.get("MINDMAP_B64"):
        tpl = tpl.replace("<!--IF:MINDMAP-->", "").replace("<!--/IF:MINDMAP-->", "")
    ch_m = re.search(r"<!--#CHAPTER-->(.*?)<!--/CHAPTER-->", tpl, re.S)
    if ch_m and "chapters" in ctx:
        block = ch_m.group(1)
        ent_m = re.search(r"<!--#ENTRY-->(.*?)<!--/ENTRY-->", block, re.S)
        ent_skel = ent_m.group(1) if ent_m else ""
        parts = []
        for ch in ctx["chapters"]:
            seg = block.replace(ent_m.group(0), "{{__ENTRIES__}}") if ent_m else block
            seg = seg.replace("{{CHAPTER_TITLE}}", html_mod.escape(ch["title"], quote=False))
            seg = seg.replace("{{CHAPTER_TIME}}", html_mod.escape(ch.get("time", ""), quote=False))
            ents = []
            for e in ch["entries"]:
                paras = "".join(f"<p>{md_inline(p)}</p>" for p in e["paras"])
                s = ent_skel
                for k, v in (("SPEAKER", e["speaker"]), ("COLOR", e.get("color", "#333")),
                             ("AVATAR", e.get("avatar", "")), ("TS", e.get("ts", "")),
                             ("PARAS_HTML", paras), ("IDX", str(e.get("idx", "")))):
                    s = s.replace("{{" + k + "}}", html_mod.escape(str(v), quote=False)
                                  if k in ("SPEAKER", "TS") else str(v))
                ents.append(s)
            seg = seg.replace("{{__ENTRIES__}}", "".join(ents))
            parts.append(seg)
        tpl = tpl[:ch_m.start()] + "".join(parts) + tpl[ch_m.end():]
    for m in re.finditer(r"\{\{(\w+)\}\}", tpl):
        key = m.group(1)
        if key in ctx:
            tpl = tpl.replace(m.group(0), str(ctx[key]))
    left = re.findall(r"\{\{(\w+)\}\}", tpl)
    if left:
        sys.exit(f"❌ 模板残留未替换占位符：{sorted(set(left))}")
    return tpl


def assign_colors(speakers: list, preset: dict) -> dict:
    out, i = {}, 0
    for sp in speakers:
        if sp in out:
            continue
        out[sp] = preset.get(sp) or PALETTE[i % len(PALETTE)]
        i += 1
    return out


# ---------- 渲染入口 ----------
def render_minutes(md_text: str, tpl: str, **head) -> str:
    data = parse_minutes_md(md_text)
    speakers = [e["speaker"] for c in data["chapters"] for e in c["entries"]]
    preset = dict(re.findall(r"([\w\s\u4e00-\u9fff]+?)=#([0-9A-Fa-f]{6})",
                             _colors_comment(tpl)))
    colors = assign_colors(speakers, preset)
    idx = 0
    for c in data["chapters"]:
        for e in c["entries"]:
            idx += 1
            e["idx"] = idx
            e["color"] = colors[e["speaker"]]
            e["avatar"] = avatar_char(e["speaker"])
    ctx = _head_ctx(md_text, **head)
    ctx["chapters"] = data["chapters"]
    ctx["SPEAKERS_LINE"] = ctx.get("SPEAKERS_LINE") or "、".join(dict.fromkeys(speakers))
    return expand(_strip_colors(tpl), ctx)


def render_doc(md_text: str, tpl: str, title=None, kicker=None, date=None,
               duration=None, speakers_line=None, source_url=None, mindmap_png=None) -> str:
    ctx = _head_ctx(md_text, title=title, kicker=kicker, date=date, duration=duration,
                    speakers_line=speakers_line, source_url=source_url, mindmap_png=mindmap_png)
    ctx["BODY"] = parse_doc_md(md_text)
    return expand(_strip_colors(tpl), ctx)


def _head_ctx(md_text, title=None, kicker=None, date=None, duration=None,
              speakers_line=None, source_url=None, mindmap_png=None) -> dict:
    meta = _meta_of(md_text)
    if title is None:
        title = re.search(r"^# (.+)$", md_text, re.M)
        title = title.group(1).strip() if title else "访谈纪要"
    ml = meta.get("会议时间", "")
    parts = [p.strip() for p in ml.split("·")]
    return {"TITLE": html_mod.escape(str(title), quote=False),
            "KICKER": kicker or "MEETING MINUTES",
            "DATE": date or (parts[0] if parts else ""),
            "DURATION": duration or (parts[1].replace("时长", "").strip() if len(parts) > 1 else ""),
            "SPEAKERS_LINE": speakers_line or meta.get("发言人", ""),
            "SOURCE_URL": source_url or meta.get("来源", ""),
            "MINDMAP_B64": (base64.b64encode(Path(mindmap_png).read_bytes()).decode()
                            if mindmap_png else "")}


def _colors_comment(tpl: str) -> str:
    m = re.search(r"<!--COLORS: (.*?)-->", tpl, re.S)
    return m.group(1) if m else ""


def _strip_colors(tpl: str) -> str:
    return re.sub(r"<!--COLORS: .*?-->\n?", "", tpl, flags=re.S)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("md", type=Path)
    ap.add_argument("--template", help="<set>/<doc>，如 research-report/minutes")
    ap.add_argument("--mindmap", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--title")
    ap.add_argument("--kicker")
    ap.add_argument("--source-url")
    ap.add_argument("--list-templates", action="store_true")
    a = ap.parse_args()
    if a.list_templates:
        for d in sorted(TPL_DIR.iterdir()):
            if d.is_dir():
                docs = ",".join(sorted(p.stem for p in d.glob("*.html")))
                print(f"{d.name}: {docs}")
        return
    tpl_path = TPL_DIR / f"{a.template}.html"
    if not tpl_path.exists():
        sys.exit(f"❌ 模板不存在：{tpl_path}（--list-templates 查看）")
    md_text = a.md.read_text(encoding="utf-8")
    tpl = tpl_path.read_text(encoding="utf-8")
    doc_type = a.template.split("/")[-1]
    if doc_type == "minutes":
        out = render_minutes(md_text, tpl, title=a.title, kicker=a.kicker, source_url=a.source_url,
                             mindmap_png=a.mindmap)
    else:
        out = render_doc(md_text, tpl, title=a.title, kicker=a.kicker, source_url=a.source_url,
                         mindmap_png=a.mindmap)
    out_path = a.out or a.md.with_suffix(".html")
    out_path.write_text(out, encoding="utf-8")
    print(f"✅ {a.template} ← {a.md.name} → {out_path}（{out_path.stat().st_size/1024:.0f} KB）")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 测试通过**

Run: `python -m pytest tests/test_render.py -q`
Expected: 7 passed。（`render_doc` 测试需要一个最小 tpl 参数——测试里传 `"tpl"` 纯文本模板，函数只做注入，无需占位）

- [ ] **Step 5: Commit**

```bash
git add scripts/render.py tests/test_render.py && git commit -m "feat: render engine with placeholder expansion (TDD)"
```

---

### Task 7: research-report 模板 set（从本次产物抽取）

**Files:** Create `reference\templates\research-report\minutes.html`、`summary.html`

- [ ] **Step 1: 生成纪要模板**

源文件：`D\OceanDemo路演访谈会议纪要（外发版）.html`（本次终版）。复制到 `reference\templates\research-report\minutes.html`，然后做如下精确替换（保留全部 CSS/JS）：

1. `<title>…</title>` 整行 → `<title>{{TITLE}}</title>`
2. masthead 区：`<div class="mast-kicker">…</div>` 内文 → `{{KICKER}}`；`<h1>…</h1>` 内文 → `{{TITLE}}`；`mast-sub` 内文 → `{{SPEAKERS_LINE}}`
3. meta-table 四行 `<td>` 内容分别 → `{{DATE}}（时长 {{DURATION}}）`、`{{SPEAKERS_LINE}}`、`{{SPEAKERS_LINE}}`、`{{SOURCE_URL}}`（th 标签保留）
4. 图例区：整段 `<div class="legend">…</div>` 的**内容**（`legend-cap` 后到 filterCount 前）→ 保留 `legend-cap` 与 `#filterCount`，中间动态 chips 删除（筛选 JS 用 data-speaker 自动绑定，chips 由渲染注入：在原位置放 `<!--#CHAPTER-->` 之外的说明：本模板图例由下方 CHAPTER 块生成前的 JS 初始化生成——**简化方案**：图例 chips 改为静态省略，仅保留 filterCount，JS 的 chip 绑定改为对 `.entry` 上方一段 `{{SPEAKERS_LINE}}` 文本的说明；**最终采用**：在 legend 内插入一个隐藏的 `<!--#ENTRY-->{{SPEAKER}}<!--/ENTRY-->` 复用块不可行，故本模板图例区仅保留 `已筛选` 指示与说明文字"按发言人姓名搜索筛选"）——执行时按此最终方案落地：删除 chips 按钮及其 JS 绑定段落，保留搜索/进度/回顶/Tab 逻辑
5. `<div class="content">` 内：masthead 之后到 `</div></div></section>` 之前的**全部章节 `<section class="chapter">…</section>`** → 替换为章节块骨架：

```html
<!--#CHAPTER--><section class="chapter" id="ch-{{IDX}}">
<div class="chapter-h"><h2>{{CHAPTER_TITLE}}</h2><span class="ch-time">{{CHAPTER_TIME}}</span></div>
<!--#ENTRY--><article class="entry" data-speaker="{{SPEAKER}}" id="e{{IDX}}">
<div class="avatar" style="background:{{COLOR}}">{{AVATAR}}</div>
<div class="card-main">
<div class="card-head"><span class="sname" style="color:{{COLOR}}">{{SPEAKER}}</span>
<span class="ts">{{TS}}</span><span class="idx">#{{IDX}}</span></div>
<div class="txt">{{PARAS_HTML}}</div></div></article><!--/ENTRY-->
</section><!--/CHAPTER-->
```

6. 搜索 JS 中 `document.querySelectorAll('.chip')` 段落删除；`applyFilter` 简化为仅按搜索词显隐（保留 `.nomatch` 逻辑）
7. `tab-summary`/`tab-mindmap` 两个 section 整段删除（本模板只做纪要单页），导航 Tab 按钮仅剩装饰性当前页标识或整段 nav tabs 简化为标题条
8. 文件头加一行注释 `<!-- research-report/minutes · 抽取自 OceanDemo 项目终版 · 占位符见 doctor --check-template -->`

- [ ] **Step 2: 生成总结模板**

源文件：`D\OceanDemo路演访谈会议总结（网页版）.html`。复制为 `summary.html`，替换：`<title>` → `{{TITLE}}`；kicker → `{{KICKER}}`；h1 → `{{TITLE}}`；`.page` 内正文 `<h1>` 之后到 `<h2>附：思维导图</h2>` 之前的全部内容 → `{{BODY}}`；导图 `<img …src="data:image/png;base64,…">` → `<img class="mindmap-img" alt="思维导图" src="data:image/png;base64,{{MINDMAP_B64}}">`；footer 链接 href → `{{SOURCE_URL}}`、文字 `飞书妙记` 保留。

- [ ] **Step 3: 校验与渲染验证**

```bash
python scripts/doctor.py --check-template reference/templates/research-report/minutes.html
python scripts/doctor.py --check-template reference/templates/research-report/summary.html
python scripts/render.py tests/fixtures/minutes_polished.md --template research-report/minutes --out runs/_rr_minutes.html
python scripts/render.py tests/fixtures/summary.md --template research-report/summary --mindmap "E:\LLMproject\PersonalAffairs\远洋示例\20180827-OceanDemo路演访谈\会议总结思维导图.png" --out runs/_rr_summary.html
```
Expected: 两模板合法；两 HTML 生成无"残留占位符"错误；浏览器抽查（http.server + Playwright 截图）视觉与本次终版一致。

- [ ] **Step 4: Commit**

```bash
git add reference/templates/research-report && git commit -m "feat: research-report template set"
```

---

### Task 8: clean-doc 模板 set

**Files:** Create `reference\templates\clean-doc\{minutes,summary}.html`

- [ ] **Step 1: summary.html**

以 Task 7 Step 2 的总结模板为基础，仅改 CSS 变量行：`--navy:#1B2A4A;--gold:#a8842c;--bg:#f6f4ee` → `--navy:#374151;--gold:#6B7280;--bg:#ffffff`，kicker 默认文案改 `SUMMARY`；其余占位符结构一致。

- [ ] **Step 2: minutes.html（零 JS 纯文档版纪要，全新精简实现）**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
:root{--ink:#26282e;--muted:#6b7280;--line:#e5e7eb;--navy:#374151;--gold:#6B7280;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fff;color:var(--ink);font:15.5px/1.95 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.page{max-width:860px;margin:0 auto;padding:44px 26px 60px}
.kicker{font-size:11px;letter-spacing:4px;color:var(--gold);font-weight:700;margin-bottom:10px}
h1{font-size:25px;color:var(--navy);padding-bottom:14px;border-bottom:2px solid var(--navy)}
.metas{color:var(--muted);font-size:13px;margin:14px 0 8px}
.metas span{margin-right:16px}
h2.ch{font-size:18px;color:var(--navy);margin:30px 0 6px}
.ch-time{font-size:12px;color:var(--muted)}
.entry{margin:14px 0;padding:10px 0 10px 14px;border-left:3px solid {{COLORLESS_PLACEHOLDER_REMOVED}}#d1d5db}
.entry .head{font-size:13.5px;color:var(--navy);font-weight:700}
.entry .head .ts{font-weight:400;color:var(--muted);font-size:12px;margin-left:8px}
.entry p{margin:6px 0}
strong{color:var(--navy)}
footer{max-width:860px;margin:0 auto;padding:0 26px 40px;color:#9ca3af;font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="page">
  <div class="kicker">{{KICKER}}</div>
  <h1>{{TITLE}}</h1>
  <div class="metas"><span>{{DATE}}</span><span>时长 {{DURATION}}</span><span>{{SPEAKERS_LINE}}</span></div>
<!--#CHAPTER-->
  <h2 class="ch">{{CHAPTER_TITLE}} <span class="ch-time">{{CHAPTER_TIME}}</span></h2>
<!--#ENTRY-->
  <div class="entry" style="border-left-color:{{COLOR}}">
    <div class="head">{{SPEAKER}}<span class="ts">{{TS}}</span></div>
    {{PARAS_HTML}}
  </div>
<!--/ENTRY-->
<!--/CHAPTER-->
</div>
<footer>记录来源：<a href="{{SOURCE_URL}}" style="color:#9ca3af">飞书妙记</a></footer>
</body>
</html>
```
（执行时删除 CSS 里那处笔误占位 `{{COLORLESS_PLACEHOLDER_REMOVED}}`，该行 border-left 固定色 `#d1d5db`。）

- [ ] **Step 3: 双模板校验+渲染验证**

```bash
python scripts/doctor.py --check-template reference/templates/clean-doc/minutes.html
python scripts/render.py tests/fixtures/minutes_polished.md --template clean-doc/minutes --out runs/_cd.html
python scripts/render.py tests/fixtures/summary.md --template clean-doc/summary --out runs/_cds.html
```
Expected: 全绿；浏览器截图抽查。

- [ ] **Step 4: Commit**

```bash
git add reference/templates/clean-doc && git commit -m "feat: clean-doc template set"
```

---

### Task 9: modern-card 模板 set（新设计，亮色应用风）

**Files:** Create `reference\templates\modern-card\{minutes,summary}.html`

- [ ] **Step 1: minutes.html（完整实现）**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
:root{--bg:#f4f6fa;--card:#fff;--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--accent:#2563EB;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:15.5px/1.9 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:26px 20px 80px}
.hero{background:linear-gradient(135deg,#1e3a8a,#2563EB 55%,#4F46E5);border-radius:18px;color:#fff;padding:32px 34px 26px;box-shadow:0 12px 32px rgba(30,58,138,.25)}
.kicker{font-size:11px;letter-spacing:3px;opacity:.85;margin-bottom:8px}
.hero h1{font-size:26px;margin-bottom:10px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.chips span{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.3);padding:3px 12px;border-radius:999px;font-size:12.5px}
h2.ch{font-size:18px;margin:26px 0 10px;color:#1e3a8a}
.entry{display:flex;gap:14px;background:var(--card);border:1px solid var(--line);border-left:4px solid #ddd;border-radius:14px;padding:15px 19px;margin:11px 0;transition:box-shadow .15s}
.entry:hover{box-shadow:0 4px 18px rgba(31,41,55,.1)}
.avatar{width:40px;height:40px;border-radius:50%;color:#fff;display:flex;align-items:center;justify-content:center;font-size:17px;font-weight:600;flex-shrink:0;margin-top:2px}
.main{flex:1;min-width:0}
.head{display:flex;align-items:baseline;gap:10px;margin-bottom:3px}
.sname{font-weight:700;font-size:14px}
.ts{font-size:12px;color:var(--muted)}
.idx{font-size:11px;color:#c0c6d0;margin-left:auto}
p{margin:7px 0}
strong{color:#1e3a8a}
footer{max-width:960px;margin:0 auto;padding:0 20px 40px;color:#9ca3af;font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div class="kicker">{{KICKER}}</div>
    <h1>{{TITLE}}</h1>
    <div class="chips"><span>{{DATE}}</span><span>{{DURATION}}</span><span>{{SPEAKERS_LINE}}</span></div>
  </div>
<!--#CHAPTER-->
  <h2 class="ch">{{CHAPTER_TITLE}}（{{CHAPTER_TIME}}）</h2>
<!--#ENTRY-->
  <article class="entry" style="border-left-color:{{COLOR}}">
    <div class="avatar" style="background:{{COLOR}}">{{AVATAR}}</div>
    <div class="main">
      <div class="head"><span class="sname" style="color:{{COLOR}}">{{SPEAKER}}</span><span class="ts">{{TS}}</span><span class="idx">#{{IDX}}</span></div>
      {{PARAS_HTML}}
    </div>
  </article>
<!--/ENTRY-->
<!--/CHAPTER-->
</div>
<footer>记录来源：<a href="{{SOURCE_URL}}" style="color:#9ca3af">飞书妙记</a></footer>
</body>
</html>
```

- [ ] **Step 2: summary.html**

复用 Task 8 clean-doc summary 的占位符结构（`{{BODY}}` 型），CSS 换为：`--bg:#f4f6fa`、卡片式 h2（`border-left:4px solid var(--accent)` 蓝）、正文 max-width 860、p/li 风格同上表。（执行时以 clean-doc/summary.html 为底改配色即可，占位符不动）

- [ ] **Step 3: 校验+渲染+截图验证，Commit**

```bash
python scripts/doctor.py --check-template reference/templates/modern-card/minutes.html
python scripts/render.py tests/fixtures/minutes_polished.md --template modern-card/minutes --out runs/_mc.html
git add reference/templates/modern-card && git commit -m "feat: modern-card template set"
```

---

### Task 10: chat-bubble 模板 set（新设计）

**Files:** Create `reference\templates\chat-bubble\{minutes,summary}.html`

- [ ] **Step 1: minutes.html（完整实现；气泡按奇偶发言人左右分布）**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#eef1f5;font:15px/1.85 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#1f2937}
.wrap{max-width:860px;margin:0 auto;padding:26px 18px 70px}
.headcard{background:#fff;border-radius:16px;padding:22px 26px;margin-bottom:18px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
.kicker{font-size:11px;letter-spacing:3px;color:#6b7280;margin-bottom:6px}
h1{font-size:22px;color:#111827}
.meta{color:#6b7280;font-size:13px;margin-top:8px}
h2.ch{font-size:15px;color:#6b7280;text-align:center;margin:22px 0 14px}
h2.ch::before,h2.ch::after{content:" — "}
.row{display:flex;gap:10px;margin:12px 0;align-items:flex-start}
.row.right{flex-direction:row-reverse}
.avatar{width:38px;height:38px;border-radius:12px;color:#fff;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:600;flex-shrink:0}
.bubble{max-width:76%;background:#fff;border-radius:4px 14px 14px 14px;padding:10px 14px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.row.right .bubble{border-radius:14px 4px 14px 14px}
.who{font-size:12px;color:#6b7280;margin-bottom:3px}
.who .ts{margin-left:8px;font-size:11px}
p{margin:5px 0}
strong{color:#111827}
footer{max-width:860px;margin:0 auto;padding:0 18px 40px;color:#9ca3af;font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <div class="headcard">
    <div class="kicker">{{KICKER}}</div>
    <h1>{{TITLE}}</h1>
    <div class="meta">{{DATE}} · {{DURATION}} · {{SPEAKERS_LINE}}</div>
  </div>
<!--#CHAPTER-->
  <h2 class="ch">{{CHAPTER_TITLE}}（{{CHAPTER_TIME}}）</h2>
<!--#ENTRY-->
  <div class="row {{CLASS_ODD_EVEN_REMOVED}}">
    <div class="avatar" style="background:{{COLOR}}">{{AVATAR}}</div>
    <div class="bubble" style="border-top:2px solid {{COLOR}}">
      <div class="who">{{SPEAKER}}<span class="ts">{{TS}}</span></div>
      {{PARAS_HTML}}
    </div>
  </div>
<!--/ENTRY-->
<!--/CHAPTER-->
</div>
<footer>记录来源：<a href="{{SOURCE_URL}}" style="color:#9ca3af">飞书妙记</a></footer>
</body>
</html>
```
执行修正：`.row` 的 class 固定 `row`（左右分布需 JS：模板底部追加 6 行小脚本按 `data-speaker` 哈希交替加 `right` 类）：
```html
<script>document.querySelectorAll('.row').forEach((r,i)=>{if(i%2)r.classList.add('right')})</script>
```
（以行序奇偶近似左右分布，无需改 render.py。）

- [ ] **Step 2: summary.html**（以 clean-doc/summary.html 为底：`--bg:#eef1f5`、h1 不带下边框改圆角白卡包裹 kicker+h1+meta、h2 左侧圆点 `::before{content:"● "}`——占位符结构不动）

- [ ] **Step 3: 校验+渲染+截图验证，Commit**

```bash
python scripts/doctor.py --check-template reference/templates/chat-bubble/minutes.html
python scripts/render.py tests/fixtures/minutes_polished.md --template chat-bubble/minutes --out runs/_cb.html
git add reference/templates/chat-bubble && git commit -m "feat: chat-bubble template set"
```

---

### Task 11: timeline 模板 set（新设计）

**Files:** Create `reference\templates\timeline\{minutes,summary}.html`

- [ ] **Step 1: minutes.html（完整实现）**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fafaf7;font:15px/1.9 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#2d2a24}
.wrap{max-width:860px;margin:0 auto;padding:40px 22px 70px}
.kicker{font-size:11px;letter-spacing:4px;color:#8a8471;font-weight:700;margin-bottom:8px}
h1{font-family:Georgia,'STZhongsong','SimSun',serif;font-size:24px;color:#2d2a24;padding-bottom:14px;border-bottom:1px solid #ddd8cc}
.meta{color:#8a8471;font-size:13px;margin:12px 0 6px}
.tl{margin-top:26px;border-left:2px solid #d8d2c0;padding-left:26px}
.ch{font-family:Georgia,'STZhongsong','SimSun',serif;font-size:17px;color:#2d2a24;margin:26px 0 10px}
.ch small{font-family:inherit;color:#8a8471;font-size:12px;margin-left:10px}
.node{position:relative;margin:16px 0}
.node::before{content:"";position:absolute;left:-33px;top:8px;width:11px;height:11px;border-radius:50%;background:#fff;border:3px solid var(--c,#6b7280)}
.node .ts{font-size:12px;color:#8a8471;font-variant-numeric:tabular-nums}
.node .who{font-weight:700;font-size:14px;color:var(--c,#6b7280)}
.node .card{background:#fff;border:1px solid #e6e1d3;border-radius:6px;padding:12px 16px;margin-top:6px}
p{margin:6px 0}
strong{color:#2d2a24}
footer{max-width:860px;margin:0 auto;padding:0 22px 40px;color:#a49e8c;font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <div class="kicker">{{KICKER}}</div>
  <h1>{{TITLE}}</h1>
  <div class="meta">{{DATE}} · {{DURATION}} · {{SPEAKERS_LINE}}</div>
  <div class="tl">
<!--#CHAPTER-->
    <div class="ch">{{CHAPTER_TITLE}}<small>{{CHAPTER_TIME}}</small></div>
<!--#ENTRY-->
    <div class="node" style="--c:{{COLOR}}">
      <span class="ts">{{TS}}</span> <span class="who">{{SPEAKER}}</span>
      <div class="card">{{PARAS_HTML}}</div>
    </div>
<!--/ENTRY-->
<!--/CHAPTER-->
  </div>
</div>
<footer>记录来源：<a href="{{SOURCE_URL}}" style="color:#a49e8c">飞书妙记</a></footer>
</body>
</html>
```

- [ ] **Step 2: summary.html**（以 clean-doc/summary.html 为底：底色 `#fafaf7`、h2 前加 `::before{content:"▸ "}`、正文 max-width 800——占位符结构不动）

- [ ] **Step 3: 校验+渲染+截图验证，Commit**

```bash
python scripts/doctor.py --check-template reference/templates/timeline/minutes.html
python scripts/render.py tests/fixtures/minutes_polished.md --template timeline/minutes --out runs/_tl.html
git add reference/templates/timeline && git commit -m "feat: timeline template set"
```

---

### Task 12: SKILL.md + reference 手册

**Files:** Create `SKILL.md`、`reference\pipeline.md`、`reference\feishu-api.md`

- [ ] **Step 1: 写 SKILL.md（frontmatter + 工作流 + 兜底；正文按下述骨架完整撰写，命令与 Task 2-11 一致）**

```markdown
---
name: interview-report-kit
description: "飞书妙记访谈实录→纪要/总结 HTML 报告套件。触发条件：用户提供飞书妙记链接（+可选本地音频）要求生成访谈纪要、会议总结、网页版报告；或说'整理访谈实录''生成访谈纪要HTML'；或仅提供访谈 markdown 要求套模板渲染 HTML。"
---

# interview-report-kit

输入：飞书妙记 URL（+可选本地音频）。输出：可编辑的中间 markdown + 访谈纪要 HTML + 会议总结 HTML（5 套模板任选）。

## 环境前置
- python 依赖：`pip install -r <skill>/requirements.txt`；`playwright install chromium`
- 系统依赖：ffmpeg、Node+mmdc（`npm i -g @mermaid-js/mermaid-cli`）
- 自检：`python scripts/doctor.py`（全 ✅ 才继续；缺啥按提示装）

## 工作流（9 环节）
（按设计文档 §6 的表逐环节写：命令行 + agent 动作 + 兜底。
①python scripts/fetch_minutes.py <url> —— 失败按 reference/feishu-api.md 手动爬
②python scripts/build_transcript.py minutes_raw.json
③python scripts/asr.py <音频>（无音频跳过③④；CPU 约 1.2× 时长，建议后台跑）
④读双源逐段比对 → 写 corrections.json → python scripts/apply_corrections.py …（原则见 reference/pipeline.md）
⑤按 pipeline.md 润色（合并时间块/书面化/逻辑分段/章节）→ 直接改写 会议实录（修正）.md
⑥写 会议总结.md（结构见 pipeline.md）
⑦写 思维导图.mmd → mmdc -i … -o …png -w 1600 -b white
⑧python scripts/render.py ×2（--list-templates 看全部；纪要与总结建议同 set）
⑨可选：本地 http.server + 浏览器截图抽查）

## 产物结构
（列出全部输出文件与说明，同设计文档 §2）

## 注意
- 修正/润色/总结/导图均为 markdown/mmd 可编辑产物；用户改完 md 只需重跑 ⑧
- render.py 可独立使用：任意 md + 模板 → HTML
- 模板即完整 HTML：复制一份改样式即成新模板，`doctor.py --check-template` 校验
```

- [ ] **Step 2: 写 reference/pipeline.md**（LLM 环节操作细则，内容来自本会话验证过的实践：校正双源原则/规则格式/润色合并与标注规范/总结章节结构/mindmap 写法与渲染/关键数字 grep 核对清单方法/（录音模糊）标注约定）

- [ ] **Step 3: 写 reference/feishu-api.md**（三端点 URL+参数+字段路径+分页策略；MCP 浏览器手动兜底完整步骤：网络面板发现→页面上下文 fetch→Blob 触发下载落盘；登录态丢失处理）

- [ ] **Step 4: Commit**

```bash
git add SKILL.md reference/pipeline.md reference/feishu-api.md && git commit -m "docs: skill manifest and reference manuals"
```

---

### Task 13: E2E 终验（真实妙记 URL + 真实数据）

**Files:** 无新文件；验证产物落在 `runs/e2e/`

- [ ] **Step 1: 5 套模板全量渲染夹具**

```bash
cd "C:\Users\bunny\.agents\skills\interview-report-kit"
for s in research-report clean-doc modern-card chat-bubble timeline; do
  python scripts/render.py tests/fixtures/minutes_polished.md --template $s/minutes --out runs/e2e/$s-minutes.html
  python scripts/render.py tests/fixtures/summary.md --template $s/summary --mindmap "E:\LLMproject\PersonalAffairs\远洋示例\20180827-OceanDemo路演访谈\会议总结思维导图.png" --out runs/e2e/$s-summary.html
done
```
Expected: 10 个 HTML 全部生成、零"残留占位符"错误。

- [ ] **Step 2: 真实爬取回归（本次妙记 URL，登录态已持久）**

```bash
python scripts/fetch_minutes.py "https://demo.feishu.cn/minutes/demotoken0a1b2c3d4e" --out runs/e2e/minutes_raw.json
python scripts/build_transcript.py runs/e2e/minutes_raw.json --out runs/e2e/会议实录.md
```
Expected: `150 段 / 8 人`，与夹具一致（diff 首尾段）。

- [ ] **Step 3: 视觉抽查**

`python -m http.server` 于 skill 目录 + Playwright 逐个截图 10 个 HTML；核对：章节结构完整、发言人着色、无未替换占位符、导图显示。

- [ ] **Step 4: doctor 全绿 + 自包含检查**

```bash
python scripts/doctor.py
grep -rn "E:\\\\LLMproject\|VideoSkills\|video-summary" scripts/ SKILL.md reference/*.md || echo CLEAN
```
Expected: doctor 全 ✅；grep 无外部路径引用（CLEAN）。

- [ ] **Step 5: 终验提交与交付报告**

```bash
git add -A && git commit -m "test: e2e validation with real meeting data"
```
向用户报告：5 set 模板截图、E2E 结果、skill 使用入口（SKILL.md 触发词）。

---

## Self-Review 记录

1. **Spec 覆盖**：设计文档 §2 产物/§3 目录/§4 模板规范与 5 set/§5 CLI/§6 工作流/§7 依赖/§8 验收 → Task 0/1-5/6/7-11/12/13 一一对应；§8 验收标准 1-5 由 Task 13 Step 1-4 覆盖。✓
2. **占位符扫描**：Task 8/10 中两处"执行时修正"注记（clean-doc CSS 笔误占位、chat-bubble row class）均已给出最终落地写法，非 TBD。✓
3. **类型一致性**：corrections.json 字段（old/new/expect/basis）在 Task 5 与 Task 12 pipeline.md 中一致；模板占位符集合与 doctor.KNOWN_KEYS、render.py ctx 键一致；minutes_raw.json 字段（s/t/x）在 Task 2/4 一致。✓
