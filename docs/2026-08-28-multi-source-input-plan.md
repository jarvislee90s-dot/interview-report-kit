# 输入端多源兼容（v1.1/v1.2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** interview-report-kit 输入端从"飞书妙记专用"扩展为多源（A1 网页类：妙记/腾讯会议/网页兜底；A2 本地文档 md/txt/word/pdf；B 本地录音），输出分级为双产物/单产物快速线。

**Architecture:** 所有新适配器统一收口到现有契约 `minutes_raw.json`（`paras:[{s,t,x}]`），下游 build_transcript → 润色/总结 → render 基本不动。脚本只做确定性的事（取数/解码/提取/机械替换），结构识别交给 agent。契约微扩：`t` 可缺省、新增 `source_label`。

**Tech Stack:** Python 3.10+（stdlib + playwright + python-docx + pypdf），FunASR（paraformer-zh + cam++，Phase 3 可选依赖），pytest。

**Spec:** `docs/2026-08-28-multi-source-input-design.md`（产品说明书；本 plan 承载全部实现细节）

**通用约定：**
- 工作目录 = 仓库根 `E:\LLMproject\Github\interview-report-kit`；`python` = python3.10+。
- 历史文档 `docs/2026-08-27-*.md` 是 v1.0 存档，**不改**。
- 每个任务的"Commit"步骤都必须执行；测试命令统一 `python -m pytest -q`（或指定文件 `-v`）。
- Windows 控制台 GBK：所有新脚本必须带与现有脚本一致的 GBK 容错块（模板见 Task 4 完整文件）。

---

## Phase 1：快速线 + 命名清理

### Task 1: `fetch_minutes.py` → `fetch_feishu.py` 更名与全库引用同步

**Files:**
- Rename: `scripts/fetch_minutes.py` → `scripts/fetch_feishu.py`
- Modify: `scripts/{build_transcript,asr,doctor,apply_corrections,render}.py`（各 1 处同步块注释）、`SKILL.md`、`README.md`、`reference/feishu-api.md`

- [x] **Step 1: git mv 更名**

```bash
git mv scripts/fetch_minutes.py scripts/fetch_feishu.py
```

- [x] **Step 2: 批量替换引用（同步块注释 + 文档）**

```bash
sed -i 's/fetch_minutes\.py/fetch_feishu.py/g' scripts/*.py SKILL.md README.md reference/feishu-api.md
```

- [x] **Step 3: 验证无残留（历史文档除外）**

Run: `grep -rn "fetch_minutes" --include="*.py" --include="*.md" . | grep -v ".git/" | grep -v "docs/2026-08-2"`
Expected: 无输出（`docs/2026-08-27-*.md` 与 `docs/2026-08-28-*.md` 属历史/spec 存档，允许保留）

- [x] **Step 4: 语法与测试回归**

Run: `python -c "import ast;ast.parse(open('scripts/fetch_feishu.py',encoding='utf-8').read())" && python -m pytest -q`
Expected: `SYNTAX OK`（无输出即通过）；测试全部 PASS

- [x] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: fetch_minutes.py 更名 fetch_feishu.py，全库引用同步（多源化命名清理第 1 步）"
```

### Task 2: `speaker_check.py` 公共检测 + 接线 fetch_feishu

**Files:**
- Create: `scripts/speaker_check.py`
- Modify: `scripts/fetch_feishu.py`（主流程尾部，约 143-147 行区域）
- Test: `tests/test_speaker_check.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_speaker_check.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import speaker_check as SC  # noqa: E402


def test_stats_counts_nonempty_speakers():
    assert SC.speaker_stats([{"s": "甲", "x": "1"}, {"s": "  ", "x": "2"}, {"x": "3"}]) == (3, 1)


def test_warn_fires_when_all_empty(capsys):
    assert SC.warn_if_no_speakers([{"s": "", "x": "a"}]) is True
    assert "无发言人" in capsys.readouterr().out


def test_warn_silent_when_named(capsys):
    assert SC.warn_if_no_speakers([{"s": "甲", "x": "a"}]) is False
    assert capsys.readouterr().out == ""
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_speaker_check.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'speaker_check'`）

- [x] **Step 3: 最小实现**

```python
# -*- coding: utf-8 -*-
"""speaker_check.py —— paras 发言人统计与全员无发言人告警（fetch_feishu / fetch_tencent /
build_transcript 复用）。场景 5：无发言人来源自动降级快速总结线。"""


def speaker_stats(paras) -> tuple:
    """返回 (总段数, 有名段数)。"""
    total = len(paras)
    named = sum(1 for p in paras if str(p.get("s") or "").strip())
    return total, named


def warn_if_no_speakers(paras) -> bool:
    """全员无发言人时打印告警并返回 True（降级快速总结线的判定依据）。"""
    total, named = speaker_stats(paras)
    if total and named == 0:
        print("⚠️ 该来源无发言人信息：无法生成按发言人组织的纪要，将走快速总结线"
              "（完成后提醒用户：补发言人信息才能出访谈纪要.html）——见 SKILL.md 第 0 环节场景 5。")
        return True
    return False
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_speaker_check.py -v`
Expected: 3 passed

- [x] **Step 5: 接线 fetch_feishu.py（检测 + source_label）**

在 `scripts/fetch_feishu.py` 顶部 import 区（`from pathlib import Path` 之后）加：

```python
from speaker_check import warn_if_no_speakers
```

把主流程尾部（`speakers = list(dict.fromkeys(...)` 之前、`if total and len(paras) < total * 0.9:` 校验块之后）改为：

```python
    warn_if_no_speakers(paras)
    data["source_label"] = "飞书妙记"
    speakers = list(dict.fromkeys(q.get("s") for q in paras if q.get("s")))
```

- [x] **Step 6: 回归 + Commit**

Run: `python -m pytest -q`
Expected: 全部 PASS

```bash
git add scripts/speaker_check.py scripts/fetch_feishu.py tests/test_speaker_check.py
git commit -m "feat: speaker_check 公共无发言人检测；fetch_feishu 写 source_label 并接线告警"
```

### Task 3: SKILL.md 第 0 环节路由 + 快速总结线 + pipeline.md 快速总结原则

**Files:**
- Modify: `SKILL.md`（frontmatter / §1 / §3 开头 / §3 末尾）
- Modify: `reference/pipeline.md`（文末追加 §6）

- [ ] **Step 1: 改写 SKILL.md frontmatter description**

将 SKILL.md 第 3 行替换为：

```yaml
description: "会议/访谈实录→纪要/总结 HTML 报告套件。触发条件：用户提供会议转写链接（飞书妙记、腾讯会议录制分享）或本地纪要文档（md/txt/word/pdf）或本地录音，要求生成访谈纪要、会议总结、网页版报告；或说'整理访谈实录''生成访谈纪要HTML'；或仅提供访谈/纪要 markdown 要求套模板渲染 HTML。"
```

- [ ] **Step 2: 改写 §1 定位的输入行**

将：

```markdown
输入：**飞书妙记 URL**（必须）+ **本地音频/视频文件**（可选，用于交叉校正）。
```

替换为：

```markdown
输入（详见第 0 环节输入路由）：**粗略纪要来源**（A1 网页类——飞书妙记 URL、腾讯会议录制分享、其他转写网页；A2 本地文档——md/txt/word/pdf）和/或**本地录音**（B——可分发言人转录，或快速总结）。
```

- [ ] **Step 3: §3 标题下插入第 0 环节**

将 `## 3. 工作流（9 环节）` 替换为：

```markdown
## 3. 工作流（⓪~⑨ 环节）

### ⓪ 输入路由（先判断走哪条线）

| 输入形态 | 入口 | 输出 |
|---|---|---|
| 飞书妙记 URL（`*.feishu.cn/minutes/*`） | ① `fetch_feishu.py` | 双产物 |
| 腾讯会议录制分享（`meeting.tencent.com/cw/*`） | ①′ `fetch_tencent.py`（Phase 2 交付） | 双产物 |
| 其他转写网页 | agent 浏览器复制正文存 txt → `extract_text.py` 同 A2 通道（Phase 2 交付） | 双产物 |
| 本地纪要文档（md/txt/word/pdf） | `extract_text.py` + agent 结构化（Phase 2 交付） | 双产物 |
| 仅本地录音 + 要区分发言人 | `asr_diarize.py` + 对话式标记（Phase 3 交付） | 双产物 |
| 仅本地录音 + 快速 | ③ `asr.py` → 快速总结线（见 ⑨ 后） | 仅 会议总结.html |
| 已有规范纪要/总结 md | 直接 ⑧ | 视 md 类型 |

- 纪要来源 + 本地录音同传 → ③④ 交叉校对线（双产物）。
- 抓取后发现**全员无发言人**（环节 ①~② 会警告）→ 降级快速总结线，完成后提醒用户：补发言人信息才能出访谈纪要.html。
- 仅录音时先问用户："需要区分发言人出纪要，还是快速出总结？"
```

- [ ] **Step 4: ⑨ 之后追加快速总结线小节**

在 SKILL.md `### ⑨ 验证（可选）` 小节之后、`## 4. 产物结构` 之前插入：

```markdown
### 快速总结线（仅录音 · 单产物，跳过 ①②④⑤）

1. `python <skill>/scripts/asr.py <音频/视频文件> --outdir asr_runs/<名称>`（同 ③）。
2. Agent 读 `transcript.txt`，按 `reference/pipeline.md` §6 快速总结原则直接写 `会议总结.md`（meta 注明"来源：本地录音 faster-whisper 转录（快速模式，未经发言人区分）"）。
3. ⑦ 思维导图（默认生成；用户明确要求"最快"时省略）→ ⑧ 仅渲染 summary 版式。

产物：`会议总结.md` + `会议总结.html`（无 访谈纪要.html / 会议实录（修正）.md / corrections.json）。
```

- [ ] **Step 5: pipeline.md 文末追加 §6**

```markdown
## 6. 快速总结原则（仅录音 · 单产物线）

- 输入只有 `transcript.txt`（无发言人归属、无时间戳结构）——总结**不按发言人组织**，按主题分节；引用原话不标注发言人（可写"主讲人/与会者"）。
- 头部 meta：`> 来源：本地录音 faster-whisper 转录（快速模式，未经发言人区分）`；说明行注明"转写未经发言人区分与逐段校对"。
- 质量纪律不变：关键数字须能在 transcript.txt 中 grep 到出处；听不清的片段标（录音模糊），不猜。
- 思维导图默认生成（§4 原则照用）。
```

- [ ] **Step 6: Commit**

```bash
git add SKILL.md reference/pipeline.md
git commit -m "docs: SKILL.md 第 0 环节输入路由 + 快速总结线；pipeline.md 快速总结原则（场景 4）"
```

---

## Phase 2：腾讯会议 + 本地文档（A1 扩展 + A2 通道）

### Task 4: `build_transcript.py` 扩展（source_label / t 可缺省 / --rename / 无发言人警告）

**Files:**
- Modify: `scripts/build_transcript.py`（整文件替换）
- Test: `tests/test_build_transcript.py`（新建）

- [x] **Step 1: 写失败测试**

```python
# tests/test_build_transcript.py
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_transcript as B  # noqa: E402


def _run(tmp_path, data, **kw):
    j = tmp_path / "minutes_raw.json"
    j.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "会议实录.md"
    B.build(out, j, **kw)
    return out.read_text(encoding="utf-8")


def test_source_label_and_url(tmp_path):
    txt = _run(tmp_path, {"source_label": "腾讯会议录制", "url": "https://meeting.tencent.com/cw/x",
                          "paras": [{"s": "甲", "t": 61000, "x": "你好"}]})
    assert "> 来源：腾讯会议录制 https://meeting.tencent.com/cw/x" in txt
    assert "**甲** 00:01:01" in txt


def test_default_label_feishu_when_missing(tmp_path):
    txt = _run(tmp_path, {"paras": [{"s": "甲", "t": 0, "x": "你好"}]})
    assert "> 记录来源：飞书妙记" in txt


def test_missing_t_renders_no_timestamp(tmp_path):
    txt = _run(tmp_path, {"paras": [{"s": "甲", "x": "没戳"}, {"s": "乙", "t": 5000, "x": "有戳"}]})
    assert "**甲**\n" in txt and "**乙** 00:00:05" in txt
    assert "末段 00:00:05" in txt


def test_rename_maps_and_keeps_unmapped(tmp_path, capsys):
    txt = _run(tmp_path, {"paras": [{"s": "spk:0", "t": 0, "x": "a"},
                                    {"s": "spk:1", "t": 1000, "x": "b"}]},
               rename={"spk:0": "张三"})
    assert "**张三**" in txt and "**spk:1**" in txt
    assert "spk:1" in capsys.readouterr().out


def test_no_speaker_warning(tmp_path, capsys):
    _run(tmp_path, {"paras": [{"s": "", "t": 0, "x": "a"}]})
    assert "无发言人" in capsys.readouterr().out
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_build_transcript.py -v`
Expected: FAIL（`TypeError: build() got an unexpected keyword argument 'rename'` 等）

- [x] **Step 3: 整文件替换 `scripts/build_transcript.py`**

```python
# -*- coding: utf-8 -*-
"""build_transcript.py —— minutes_raw.json → 会议实录.md（逐段：**发言人** 时间戳 + 段落）。
用法：python scripts/build_transcript.py minutes_raw.json [--out 会议实录.md] [--url 来源链接]
     [--rename "spk:0=张三,spk:1=主持人"]
json 结构：{"source_label":来源名?,"total_expected":N?,"url":来源链接?,"meeting_time":会议时间?,
"paras":[{"s":发言人,"t":毫秒?,"x":文本},...]}（fetch_feishu / fetch_tencent / agent 结构化 /
asr_diarize 产出）。t 缺省输出无时间戳行；--rename 按映射改写发言人，未映射的 spk: 标签保留并提示。
"""
import argparse
import json
import sys
from pathlib import Path

from speaker_check import warn_if_no_speakers


def hmss(ms: int) -> str:
    s = ms // 1000
    return f"{s//3600:02d}:{s//60%60:02d}:{s%60:02d}"


def parse_rename(spec: str) -> dict:
    """'spk:0=张三,spk:1=主持人' → {'spk:0': '张三', ...}；格式错即退出。"""
    out = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            sys.exit(f"--rename 格式错误（应为 旧名=新名，逗号分隔）：{part}")
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    if not out:
        sys.exit("--rename 为空")
    return out


def build(md_path: Path, json_path: Path, url_override: str = None, rename: dict = None) -> None:
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit(f"json 损坏或非 UTF-8：{json_path}（{type(e).__name__}: {e}）")
    paras = raw.get("paras")
    if not paras:
        sys.exit("json 缺少 paras 数组（疑似爬取写入了错误响应体）")
    if rename:
        for p in paras:
            if p.get("s") in rename:
                p["s"] = rename[p["s"]]
        unmapped = sorted({p.get("s") for p in paras
                           if str(p.get("s") or "").startswith("spk:") and p.get("s") not in rename})
        if unmapped:
            print(f"⚠️ 未映射的说话人标签保留原名：{'、'.join(unmapped)}")
    warn_if_no_speakers(paras)
    if raw.get("total_expected") not in (None, len(paras)):
        print(f"⚠️ 警告：段数 {len(paras)} 与 total_expected {raw['total_expected']} 不符，爬取可能截断")
    speakers = list(dict.fromkeys(p.get("s") for p in paras if p.get("s")))
    url = url_override or raw.get("url")
    label = raw.get("source_label") or "飞书妙记"
    meeting_time = raw.get("meeting_time")
    lines = [
        "# 访谈会议实录",
        "",
        f"> 来源：{label} {url}" if url else f"> 记录来源：{label}",
    ]
    if meeting_time:
        lines.append(f"> 会议时间：{meeting_time}")
    last_t = paras[-1].get("t") if paras else None
    lines += [
        f"> 发言人 {len(speakers)} 人：{'、'.join(speakers)}",
        f"> 发言 {len(paras)} 段 · 末段 {hmss(int(last_t)) if last_t is not None else '-'}",
        "> 说明：本文件为原始实录，未经校对。",
        "",
        "---",
        "",
    ]
    for p in paras:
        text = " ".join(str(p.get("x", "")).split())
        if not text:
            continue
        head = f"**{p.get('s') or '—'}**"
        if p.get("t") is not None:
            head += f" {hmss(int(p['t']))}"
        lines += [head, "", text, ""]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {md_path}（{len(paras)} 段 / {len(speakers)} 人）")


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
    ap.add_argument("json_path", type=Path)
    ap.add_argument("--out", type=Path, default=Path("会议实录.md"))
    ap.add_argument("--url", default=None, help="覆盖 json 内 url")
    ap.add_argument("--rename", default=None,
                    help='发言人改名映射，如 "spk:0=张三,spk:1=主持人"（对话式标记后落名）')
    a = ap.parse_args()
    if not a.json_path.exists():
        sys.exit(f"文件不存在：{a.json_path}")
    build(a.out, a.json_path, a.url, parse_rename(a.rename) if a.rename else None)
```

（注：无 url 时的来源行从 v1.0 的 `> 记录来源：飞书妙记（自动化爬取）` 简化为 `> 记录来源：{label}`，属预期行为变化。）

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_build_transcript.py -v`
Expected: 5 passed

- [x] **Step 5: 回归（旧 fixture 行为不变）**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [x] **Step 6: Commit**

```bash
git add scripts/build_transcript.py tests/test_build_transcript.py
git commit -m "feat: build_transcript 支持 source_label/无 t 段落/--rename 改名/无发言人警告"
```

### Task 5: `render.py` 纪要版式时间戳可选

**Files:**
- Modify: `scripts/render.py:23`（ENTRY_RE）、`scripts/render.py:85`（group(2) 空值兜底）、`scripts/render.py:66`（docstring 提及）
- Test: `tests/test_render.py`（追加 2 个测试）

- [x] **Step 1: 写失败测试（追加到 tests/test_render.py 末尾）**

```python
def test_parse_entry_without_ts():
    src = "# t\n\n---\n\n## 一、章\n\n**张三**\n\n正文甲\n\n**李四** 00:00:09\n\n正文乙\n"
    data = R.parse_minutes_md(src)
    es = data["chapters"][0]["entries"]
    assert es[0]["speaker"] == "张三" and es[0]["ts"] == "" and es[0]["paras"] == ["正文甲"]
    assert es[1]["speaker"] == "李四" and es[1]["ts"] == "00:00:09"


def test_colors_work_for_spk_labels():
    colors = R.assign_colors(["spk:0", "spk:1"], {})
    assert set(colors) == {"spk:0", "spk:1"} and all(v.startswith("#") for v in colors.values())
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_render.py::test_parse_entry_without_ts -v`
Expected: FAIL（`**张三**` 行不匹配 ENTRY_RE，entries 为空或 IndexError）

- [x] **Step 3: 修改 render.py**

第 23 行：

```python
ENTRY_RE = re.compile(r"^\*\*(.+?)\*\*(?: ([\d: /–\-—]+))?$")
```

第 85 行改为：

```python
            cur_entry = {"speaker": em.group(1).strip(), "ts": (em.group(2) or "").strip(), "paras": []}
```

第 66 行 docstring 中 `` `**发言人** 时间` 开新时间块 `` 改为 `` `**发言人** [时间]` 开新时间块（时间可缺省） ``。

- [x] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_render.py -v && python -m pytest -q`
Expected: 全部 PASS（既有 150 段/53 entries 等解析行为不变）

- [x] **Step 5: Commit**

```bash
git add scripts/render.py tests/test_render.py
git commit -m "feat: render 纪要版式 ENTRY_RE 时间戳可选（承接无时间戳来源）"
```

### Task 6: `extract_text.py` 本地文档 → 纯文本

**Files:**
- Create: `scripts/extract_text.py`
- Modify: `requirements.txt`（追加 2 行）
- Test: `tests/test_extract_text.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_extract_text.py
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import extract_text as X  # noqa: E402


def test_decode_utf8_and_gbk():
    assert X.decode_bytes("你好".encode("utf-8")) == "你好"
    assert X.decode_bytes("你好".encode("gb18030")) == "你好"


def test_decode_garbage_exits():
    with pytest.raises(SystemExit):
        X.decode_bytes(b"\xff\xfe\xff\xfe")


def test_extract_md_and_txt(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("张三 00:01:23\n大家好", encoding="utf-8")
    assert X.extract_any(f) == "张三 00:01:23\n大家好"


def test_extract_docx(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("张三 00:01:23")
    d.add_paragraph("大家好")
    f = tmp_path / "a.docx"
    d.save(str(f))
    assert X.extract_any(f) == "张三 00:01:23\n大家好"


def test_extract_pdf_blank(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    f = tmp_path / "a.pdf"
    with open(f, "wb") as fh:
        w.write(fh)
    assert isinstance(X.extract_any(f), str)


def test_unsupported_ext_exits(tmp_path):
    f = tmp_path / "a.xls"
    f.write_bytes(b"x")
    with pytest.raises(SystemExit):
        X.extract_any(f)
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_extract_text.py -v`
Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 `scripts/extract_text.py`**

```python
# -*- coding: utf-8 -*-
"""extract_text.py —— 本地纪要文档（md/txt/docx/pdf）→ 纯文本 .extracted.txt（UTF-8）。
只做解码与格式提取，不做发言人/时间戳结构识别（结构化由 agent 环节完成，见 SKILL.md A2 通道）。
用法：python scripts/extract_text.py <文件> [--out <名>.extracted.txt]
"""
import argparse
import sys
from pathlib import Path

DOC_EXTS = {".md", ".txt", ".docx", ".pdf"}


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    sys.exit("❌ 文本解码失败（utf-8 / gb18030 均失败）：请用 UTF-8 或 GBK 重存文件")


def extract_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        sys.exit("未安装 python-docx：pip install python-docx")
    try:
        paras = [p.text for p in docx.Document(str(path)).paragraphs]
    except Exception as e:
        sys.exit(f"❌ docx 解析失败（{type(e).__name__}: {e}）：请在 Word 中重存或另存为 txt")
    return "\n".join(paras)


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("未安装 pypdf：pip install pypdf")
    try:
        pages = [pg.extract_text() or "" for pg in PdfReader(str(path)).pages]
    except Exception as e:
        sys.exit(f"❌ pdf 解析失败（{type(e).__name__}: {e}）：请重存或转存为 txt/docx")
    return "\n".join(pages)


def extract_any(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".md", ".txt"):
        return decode_bytes(path.read_bytes())
    if ext == ".docx":
        return extract_docx(path)
    if ext == ".pdf":
        return extract_pdf(path)
    sys.exit(f"不支持的格式 {ext}（支持 {' '.join(sorted(DOC_EXTS))}）")


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
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="默认 <名>.extracted.txt")
    a = ap.parse_args()
    if not a.file.exists():
        sys.exit(f"文件不存在：{a.file}")
    text = extract_any(a.file)
    out = a.out or a.file.with_name(a.file.stem + ".extracted.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    n_lines = len([l for l in text.splitlines() if l.strip()])
    print(f"✅ 提取完成：{n_lines} 行 / {len(text)} 字 → {out}")
    print("下一步：agent 按 SKILL.md A2 通道读取该文件，忠实结构化为 minutes_raw.json，再跑 build_transcript。")
```

- [x] **Step 4: requirements.txt 追加依赖**

文件末尾追加：

```text
python-docx>=1.1.0
pypdf>=4.0.0
```

- [x] **Step 5: 安装依赖并跑测试**

Run: `pip install -r requirements.txt && python -m pytest tests/test_extract_text.py -v`
Expected: 6 passed

- [x] **Step 6: Commit**

```bash
git add scripts/extract_text.py tests/test_extract_text.py requirements.txt
git commit -m "feat: extract_text 本地文档(md/txt/docx/pdf)→纯文本，零启发式结构识别"
```

### Task 7: `fetch_tencent.py` 腾讯会议分享页 → minutes_raw.json

**Files:**
- Create: `scripts/fetch_tencent.py`
- Test: `tests/test_fetch_tencent.py`

接口预研结论（2026-08-28 实测 `https://meeting.tencent.com/cw/NX3DWjw21f`）：公开分享免登录；页面加载自发请求 `GET /wemeet-cloudrecording-webapi/v1/minutes/detail?...&id=<share_id>&meeting_id=...&recording_id=...&lang=zh&start_pid=0&limit=20&...`；响应根级 `more:true` 表示续页（下一页把 `start_pid` 换成 `pid=<上一页末段 pid>`）；段落字段 `speaker.user_name` / `start_time`(毫秒) / `sentences[].words[].text`。

- [x] **Step 1: 写失败测试（纯函数 paras_from_pages）**

```python
# tests/test_fetch_tencent.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_tencent as T  # noqa: E402


def _page(more, paragraphs):
    return {"code": 0, "more": more, "minutes": {"paragraphs": paragraphs}}


def test_paras_from_pages_maps_filters_sorts():
    p1 = _page(True, [
        {"pid": "28", "start_time": 1335349, "speaker": {"user_name": "YY评级"},
         "sentences": [{"words": [{"text": "时间差不多了"}, {"text": "，大家下午好。"}]}]},
        {"pid": "13", "start_time": 437348, "speaker": {"user_name": "YY评级"},
         "sentences": [{"words": [{"text": "好。"}]}]},
        {"pid": "14", "start_time": 500000, "speaker": {"user_name": "甲"},
         "sentences": [{"words": []}]},  # 空文本段应被过滤
    ])
    p2 = _page(False, [
        {"pid": "30", "start_time": 437000, "speaker": {"user_name": "陈老师"},
         "sentences": [{"words": [{"text": "各位领导下午好！"}]}]},
    ])
    paras = T.paras_from_pages([p1, p2])
    assert paras == [
        {"s": "陈老师", "t": 437000, "x": "各位领导下午好！"},
        {"s": "YY评级", "t": 437348, "x": "好。"},
        {"s": "YY评级", "t": 1335349, "x": "时间差不多了，大家下午好。"},
    ]


def test_paras_from_pages_missing_speaker():
    pg = _page(False, [{"pid": "1", "start_time": 10, "speaker": None,
                        "sentences": [{"words": [{"text": "x"}]}]}])
    assert T.paras_from_pages([pg]) == [{"s": "", "t": 10, "x": "x"}]
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_fetch_tencent.py -v`
Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 `scripts/fetch_tencent.py`**

```python
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
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_fetch_tencent.py -v`
Expected: 2 passed

- [ ] **Step 5: 冒烟（可选，需人工看浏览器）**

Run: `python scripts/fetch_tencent.py "https://meeting.tencent.com/cw/NX3DWjw21f" --out runs/tencent_smoke.json`
Expected: 末行 `✅ 抓取完成：N 段 / M 人 / 末段 M:SS`（N 应为数百段量级）。跳过不阻塞（Playwright 壳不做自动化测试）。

- [x] **Step 6: Commit**

```bash
git add scripts/fetch_tencent.py tests/test_fetch_tencent.py
git commit -m "feat: fetch_tencent 腾讯会议录制分享→minutes_raw.json（接口分页取数+AI纪要参考+无发言人检测）"
```

### Task 8: `reference/tencent-api.md` 手册（手动兜底）

**Files:**
- Create: `reference/tencent-api.md`

- [x] **Step 1: 写入手册全文**

````markdown
# 腾讯会议录制分享接口手册（tencent-api.md）

`fetch_tencent.py` 的取数逻辑基于这些接口（页面上下文同源 fetch）。字段路径为 **2026-08-28 实测**
（验证页：`https://meeting.tencent.com/cw/NX3DWjw21f`）。当脚本响亮失败时，按第 3 节手动兜底。

## 1. 页面与接口链

| 步骤 | 接口 | 说明 |
|---|---|---|
| 打开 `/cw/<code>` | — | 公开分享页免登录，含 纪要（AI）/ 时间轴 / 逐字稿 三个 tab；带访问密码时页面先要密码 |
| 页面自发 | `POST /v2/api/record/get-token` | 短码换 token（无需复现，页面自己完成） |
| 页面自发 | `GET /wemeet-tapi/v2/meetlog/public/record-detail/get-multi-record-info?...&uni_record_share_id=<share_id>` | 分享元信息（标题/时间） |
| 逐字稿 | `GET /wemeet-cloudrecording-webapi/v1/minutes/detail?...&id=<share_id>&meeting_id=...&recording_id=...&lang=zh&start_pid=0&limit=20&...` | **核心**：分页逐字稿 |
| AI 纪要 | `POST /wemeet-tapi/v2/meetlog/public/record-detail/query-summary-and-note` | 页面默认 tab 自发加载 |

- `minutes/detail` 关键参数：`id`（= uni_record_share_id）、`meeting_id`、`recording_id`、`lang=zh`、首页 `start_pid=0`、`limit=20`；其余 `c_timestamp / c_nonce / rnds / trace-id` 等为每请求独立的签权类参数——**照抄观测到的模板值，每页重生成 c_timestamp（当前毫秒）与 c_nonce/rnds（随机串）即可**。
- **分页**：响应根级 `more: true` 表示还有下一页；下一页把 `start_pid=0` 换成 `pid=<上一页最后一段的 pid>`；`more` 非 true 即收敛。

## 2. 响应字段 → minutes_raw.json 契约

```text
minutes.paragraphs[]          → paras[] 一段一项
  .speaker.user_name          → s（发言人名）
  .start_time                 → t（毫秒）
  .sentences[].words[].text   → x（顺序连接；全空文本段丢弃）
  .pid                        → 分页游标（不进契约）
根级 more                      → 翻页停止条件
```

标题/会议时间为尽力而为：`document.title` 恒为"录制文件"；会议时间在页面 DOM 形如 `2024/07/19 14:13`（正文正则抓取）。二者缺失不影响下游（build_transcript 只用 url/meeting_time/source_label）。

## 3. 手动兜底步骤（fetch_tencent 失败时，agent 用 MCP 浏览器）

1. 打开分享 URL，等逐字稿区域出现（需要密码则在页面上输入）。
2. DevTools Network 过滤 `minutes/detail`，任选一条请求，Copy → Copy URL。
3. 在页面上下文（MCP evaluate / 控制台）以该 URL 为模板循环 fetch：首页原样；下一页将 `start_pid=0` 替换为 `pid=<上一页末段 pid>`，并重生成 `c_timestamp`、`c_nonce`、`rnds`；直到响应根级 `more` 不为 true。
4. 把所有页的 `minutes.paragraphs` 按 §2 映射成 `paras`，写入 `minutes_raw.json`（含 `"source_label": "腾讯会议录制"`），从 ② 继续。

## 4. 何时需要人工抓包比对

出现以下情况说明腾讯改了接口，此时才需要重新核对 §1/§2 字段：`minutes/detail` 返回 code≠0 或无 `minutes` 键；`paragraphs[].speaker / start_time / sentences` 字段名变化；分页 `pid` 游标不推进（同页重复返回，guard 2000 页内未收敛）。

## 5. 登录态

`.auth`（与 fetch_feishu 共用）仅在有访问密码/要求登录的分享页有用；公开链接不需要。换机器或损坏时删除 `.auth` 重跑。
````

- [x] **Step 2: Commit**

```bash
git add reference/tencent-api.md
git commit -m "docs: tencent-api.md 腾讯会议分享接口手册与手动兜底流程"
```

### Task 9: doctor 增项 + SKILL.md Phase 2 路由补全 + v1.1.0

**Files:**
- Modify: `scripts/doctor.py:27-33`（check_env 循环后追加）
- Modify: `SKILL.md`（⓪ 路由表去"Phase 2"标注；① 后插 ①′/①″；§4/§6 补充）

- [x] **Step 1: doctor.py check_env 追加依赖项**

在 `for mod, hint in (("playwright", ...), ("faster_whisper", ...))` 循环之后、`return 1 if bad else 0` 之前插入：

```python
    for mod, hint, optional in (("docx", "pip install python-docx", False),
                                ("pypdf", "pip install pypdf", False),
                                ("funasr", "pip install -r requirements-diarize.txt", True)):
        try:
            __import__(mod)
            item(f"python:{mod}", True)
        except ImportError:
            if optional:
                print(f"  ⚠️ python:{mod}   {hint}（可选：仅'仅录音+分发言人'线需要）")
            else:
                item(f"python:{mod}", False, hint)
```

- [x] **Step 2: SKILL.md 路由表去掉 3 处"（Phase 2 交付）"字样**

将 ⓪ 表中三行改为（"Phase 3 交付"暂保留，Task 12 处理）：

```markdown
| 腾讯会议录制分享（`meeting.tencent.com/cw/*`） | ①′ `fetch_tencent.py` | 双产物 |
| 其他转写网页 | agent 浏览器复制正文存 txt → `extract_text.py` 同 A2 通道 | 双产物 |
| 本地纪要文档（md/txt/word/pdf） | `extract_text.py` + agent 结构化（①″） | 双产物 |
```

- [x] **Step 3: SKILL.md ① 节之后插入 ①′ 与 ①″**

在 `### ① 抓取妙记 → minutes_raw.json` 小节末尾（"**响亮失败**…"那行之后）插入：

```markdown
### ①′ 腾讯会议分享 → minutes_raw.json

```bash
python <skill>/scripts/fetch_tencent.py "<录制分享URL>"
```

- URL 形如 `https://meeting.tencent.com/cw/<code>`；公开链接免登录，带访问密码则弹浏览器等待（上限 600 秒）。
- 默认顺带抓腾讯 AI 纪要存 `tencent_ai_summary.json`（⑥ 总结的参考素材，失败不阻塞；`--no-ai-summary` 关闭）。
- 预期输出：`✅ 抓取完成：N 段 / M 人 / 末段 M:SS → minutes_raw.json`；响亮失败同 ①（手册为 `reference/tencent-api.md`）。

### ①″ 本地纪要文档 → minutes_raw.json（A2 通道，其他转写网页同通道）

```bash
python <skill>/scripts/extract_text.py <md/txt/docx/pdf 文件>
```

- 产出 `<名>.extracted.txt`（纯文本）；脚本只做解码与格式提取，**不做结构识别**。
- **agent 结构化**：读该文本，忠实转录为 `minutes_raw.json`——`source_label` 填 `"本地文档：<文件名>"`；`t` 毫秒、无时间戳可省略；识别不出发言人则 `s` 留空（走场景 5 判定）；**只转录不润色**（润色是 ⑤ 的事）。写完跑 ② `build_transcript.py` 把关转换，被拒绝则修正 json 重跑。
- 其他转写网页（通义听悟/钉钉闪记/讯飞听见等）：agent 用浏览器 MCP 打开页面复制逐字稿正文存 txt，走本通道。
```

- [x] **Step 4: SKILL.md §4 产物结构、§6 兜底补两行**

§4 树中 `minutes_raw.json` 行下加：

```text
├── tencent_ai_summary.json        # ①′ 腾讯 AI 纪要参考（仅腾讯源，可选）
├── <名>.extracted.txt             # ①″ 本地文档提取的纯文本（A2 通道中间产物）
```

§6 末尾追加一段：

```markdown
`fetch_tencent.py` 失败（未捕获逐字稿请求 / 零段落 / 分页异常）时，按 **`reference/tencent-api.md`** 用 agent 浏览器在页面上下文手动分页取数补齐 `minutes_raw.json`，然后从 ② 继续。
```

- [x] **Step 5: 回归 + 打版**

Run: `python -m pytest -q && python scripts/doctor.py`
Expected: 测试全 PASS；doctor 显示 `python:docx` / `python:pypdf` ✅（funasr 视安装显示 ⚠️ 不影响退出码）

```bash
git add scripts/doctor.py SKILL.md && git commit -m "feat: doctor 增 docx/pypdf/funasr 检查；SKILL.md 补 ①′腾讯/①″本地文档通道" && git tag v1.1.0
```

---

## Phase 3：FunASR 分离转录（仅录音 + 要纪要）

### Task 10: `requirements-diarize.txt`

**Files:**
- Create: `requirements-diarize.txt`

- [x] **Step 1: 写文件**

```text
funasr>=1.1
modelscope>=1.15
torch>=2.1
```

- [x] **Step 2: Commit**

```bash
git add requirements-diarize.txt && git commit -m "build: requirements-diarize.txt（分离转录重依赖，可选安装）"
```

### Task 11: `asr_diarize.py` 录音 → 分发言人 minutes_raw.json

**Files:**
- Create: `scripts/asr_diarize.py`
- Test: `tests/test_asr_diarize.py`

- [ ] **Step 1: 写失败测试（纯函数 merge_sentences / spk_samples）**

```python
# tests/test_asr_diarize.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from asr_diarize import merge_sentences, spk_samples  # noqa: E402


def test_merge_same_spk_and_interleave():
    sents = [{"text": "大家好，", "start": 1000, "end": 2000, "spk": 0},
             {"text": "今天讲三件事。", "start": 2100, "end": 4000, "spk": 0},
             {"text": "谢谢。", "start": 4100, "end": 4500, "spk": 1},
             {"text": "不客气。", "start": 4600, "end": 5000, "spk": 1},
             {"text": "那继续。", "start": 5100, "end": 5500, "spk": 0}]
    paras = merge_sentences(sents, max_chars=200)
    assert paras == [
        {"s": "spk:0", "t": 1000, "x": "大家好，今天讲三件事。"},
        {"s": "spk:1", "t": 4100, "x": "谢谢。不客气。"},
        {"s": "spk:0", "t": 5100, "x": "那继续。"},
    ]


def test_merge_splits_long():
    sents = [{"text": "长" * 30, "start": i * 1000, "end": i * 1000 + 500, "spk": 2}
             for i in range(3)]
    paras = merge_sentences(sents, max_chars=70)
    assert len(paras) == 2 and len(paras[0]["x"]) == 60 and len(paras[1]["x"]) == 30


def test_merge_skips_empty_text():
    assert merge_sentences([{"text": "  ", "start": 0, "end": 1, "spk": 0}]) == []


def test_spk_samples_first_mid_last():
    paras = [{"s": "spk:0", "t": 0, "x": f"句{i}"} for i in range(5)]
    assert spk_samples(paras) == {"spk:0": ["句0", "句2", "句4"]}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_asr_diarize.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `scripts/asr_diarize.py`**

```python
# -*- coding: utf-8 -*-
"""asr_diarize.py —— 音频 → minutes_raw.json（FunASR 转写 + cam++ 说话人分离，s=spk:N）。
用法：python scripts/asr_diarize.py <音频/视频文件> [--outdir asr_runs/<名>] [--out minutes_raw.json]
依赖：pip install -r requirements-diarize.txt（模型自动从 ModelScope 下载，国内直连，无需 HF 授权）。
产物：asr_runs/<名>/diarize_raw.json（句级原始）+ minutes_raw.json（段级，s=spk:0/1/2…）。
结束后打印每号声音首/中/末样例句，供对话式标记（SKILL.md ③′）。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from asr import extract_wav  # 复用 ffmpeg 提取（同目录模块）
from speaker_check import warn_if_no_speakers


def merge_sentences(sentences: list, max_chars: int = 500) -> list:
    """句级 [{text,start,end,spk}]（毫秒）→ 段级 [{s,t,x}]：同人相邻合并，超长切段。"""
    paras = []
    for s in sentences:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        spk = f"spk:{s.get('spk', '?')}"
        if paras and paras[-1]["s"] == spk and len(paras[-1]["x"]) + len(text) <= max_chars:
            paras[-1]["x"] += text
        else:
            paras.append({"s": spk, "t": int(s.get("start", 0)), "x": text})
    return paras


def spk_samples(paras: list) -> dict:
    """每号声音取首/中/末段文本（前 60 字），供对话式标记辨认。"""
    by = {}
    for p in paras:
        by.setdefault(p["s"], []).append(p["x"][:60])
    return {k: [texts[i] for i in sorted({0, len(texts) // 2, len(texts) - 1})]
            for k, texts in by.items()}


def load_model():
    try:
        from funasr import AutoModel
    except ImportError:
        sys.exit("未安装 funasr：pip install -r requirements-diarize.txt")
    return AutoModel(model="paraformer-zh", vad_model="fsmn-vad",
                     punc_model="ct-punc", spk_model="cam++", disable_update=True)


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
    ap.add_argument("media", type=Path)
    ap.add_argument("--outdir", type=Path, default=None, help="默认 asr_runs/<文件名>")
    ap.add_argument("--out", type=Path, default=Path("minutes_raw.json"))
    a = ap.parse_args()
    if not a.media.exists():
        sys.exit(f"文件不存在：{a.media}")
    if shutil.which("ffmpeg") is None:
        sys.exit("未安装 ffmpeg：安装：winget install Gyan.FFmpeg 或 brew install ffmpeg")
    outdir = a.outdir or Path("asr_runs") / a.media.stem
    outdir.mkdir(parents=True, exist_ok=True)
    raw_p, json_p = outdir / "diarize_raw.json", outdir / "minutes_raw.json"

    if raw_p.exists() and json_p.exists():  # 断点续跑
        raw = json.loads(raw_p.read_text(encoding="utf-8"))
        print("  ✅ 分离转录已存在，跳过模型调用")
    else:
        extract_wav(a.media, outdir / "audio.wav")
        model = load_model()
        print("  👂 FunASR 转录 + 说话人分离（首次运行自动下载模型；CPU 耗时可观，建议后台）…")
        res = model.generate(input=str(outdir / "audio.wav"), batch_size_s=300)
        sentences = (res[0] or {}).get("sentence") or []
        raw = {"sentences": sentences}
        raw_p.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        json_p.unlink(missing_ok=True)

    paras = merge_sentences(raw.get("sentences") or [])
    if not paras:
        sys.exit("  ❌ 分离转录结果为空")
    warn_if_no_speakers(paras)
    a.out.write_text(json.dumps({"source_label": "本地录音（FunASR 分离转录）", "paras": paras},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    json_p.write_text(a.out.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  ✅ 分离转录完成：{len(paras)} 段 → {raw_p.name} / {a.out}")
    print("👂 说话人样例（供对话式标记，SKILL.md ③′）：")
    n_of = {}
    for p in paras:
        n_of[p["s"]] = n_of.get(p["s"], 0) + 1
    for spk, samples in spk_samples(paras).items():
        print(f"  {spk}（{n_of[spk]} 段）：" + " / ".join(f"「{t}」" for t in samples))
    print('下一步：问用户各号是谁，然后 build_transcript --rename "spk:0=名字,…" 落名。')
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_asr_diarize.py -v`
Expected: 4 passed

- [ ] **Step 5: 回归 + Commit**

Run: `python -m pytest -q`
Expected: 全部 PASS

```bash
git add scripts/asr_diarize.py tests/test_asr_diarize.py
git commit -m "feat: asr_diarize FunASR 分离转录→minutes_raw.json（spk:N + 样例打印 + 断点续跑）"
```

### Task 12: SKILL.md ③′ 环节 + pipeline.md 对话式标记纪律

**Files:**
- Modify: `SKILL.md`（⓪ 表去"Phase 3 交付"；③ 节后插 ③′）
- Modify: `reference/pipeline.md`（文末追加 §7）

- [ ] **Step 1: SKILL.md ⓪ 表中该行去掉"（Phase 3 交付）"**

```markdown
| 仅本地录音 + 要区分发言人 | `asr_diarize.py` + 对话式标记（③′） | 双产物 |
```

- [ ] **Step 2: SKILL.md ③ 节之后插入 ③′**

在 `### ③ 本地音频转录…` 小节末尾之后插入：

```markdown
### ③′ 录音分离转录（仅录音且要纪要时替代 ①；产出后同源不校对，跳④）

```bash
python <skill>/scripts/asr_diarize.py <音频/视频文件> [--outdir asr_runs/<名称>] [--out minutes_raw.json]
```

- 依赖 `requirements-diarize.txt`（funasr，模型从 ModelScope 自动下载）；CPU 可跑、耗时可观，建议后台运行。
- 产物：`asr_runs/<名称>/diarize_raw.json`（句级原始）+ `minutes_raw.json`（段级，`s=spk:0/1/2…`）。
- **对话式标记**：脚本结束打印每号声音首/中/末样例句。Agent 向用户提问：
  「检测到 N 个说话人——spk:0（样例…）、spk:1（样例…）——分别是谁？」
  用户回复后一步落名并出实录：

```bash
python <skill>/scripts/build_transcript.py minutes_raw.json --rename "spk:0=张三,spk:1=主持人" --out 会议实录.md
```

- 之后直接进 ⑤（同源**不校对**，无③④交叉）；用户不确定的标签保留 `spk:N` 原名（渲染时按普通发言人名展示）。
```

- [ ] **Step 3: pipeline.md 文末追加 §7**

```markdown
## 7. 对话式标记发言人（③′ 之后、② 落名）

- 提问给足辨识信息：每号 spk 的首/中/末样例句 + 段数占比；用户不确定的标签**不要硬映射**，保留 `spk:N` 原名。
- `--rename` 只做名字替换，不改段落归属；同一人被拆成两号（分离误差）不在此环节处理——如实保留，可提示用户"X 号与 Y 号疑似同人，⑤ 润色时可合并其发言块"。
- 落名后头部来源为"本地录音（FunASR 分离转录）"；说明行写"转写经 FunASR 说话人分离，发言人名为人工标记"。
```

- [ ] **Step 4: Commit**

```bash
git add SKILL.md reference/pipeline.md
git commit -m "docs: SKILL.md ③′ 录音分离转录+对话式标记；pipeline.md 标记纪律（场景 3）"
```

### Task 13: README 多源化 + 发布同步清单 + 全量验证（v1.2.0）

**Files:**
- Modify: `README.md`（tagline / 流水线图 / quick start / 目录说明 / 新增发布同步节）

- [ ] **Step 1: README 头部 tagline**

第 5 行 `**飞书妙记访谈 → 让人想读完的 HTML 报告**` 替换为：

```markdown
**会议/访谈实录 → 让人想读完的 HTML 报告**（飞书妙记 · 腾讯会议 · 本地文档 · 本地录音多源输入）
```

- [ ] **Step 2: 流水线图（约 55 行）**

```text
妙记 URL ──① fetch_feishu.py──▶ minutes_raw.json ──② build_transcript.py──▶ 会议实录.md
腾讯 /cw/ ──①′ fetch_tencent.py──▶ minutes_raw.json（同上合流）
本地文档 ──①″ extract_text.py + agent 结构化──▶ minutes_raw.json（同上合流）
仅录音 ──③′ asr_diarize.py + 对话式标记──▶ minutes_raw.json（同上合流）
仅录音快速 ──③ asr.py──▶ transcript.txt ──agent──▶ 会议总结.md（单产物）
```

（其后原有 ②~⑧ 流程描述保留不动。）

- [ ] **Step 3: quick start 命令区（约 78 行后）追加多源入口示例**

```bash
python scripts/fetch_tencent.py "<腾讯会议/cw/分享URL>"   # 公开分享免登录
python scripts/extract_text.py 会议纪要.docx              # 本地文档→纯文本，agent 再结构化
python scripts/asr_diarize.py 会议录音.m4a                # 仅录音+分发言人（需 requirements-diarize.txt）
```

- [ ] **Step 4: scripts 目录说明行（约 95 行）**

```text
├── scripts/                  # 独立 CLI：doctor / fetch_feishu / fetch_tencent / extract_text / build_transcript / asr / asr_diarize / apply_corrections / render / speaker_check
```

reference 行（约 99 行）`feishu-api.md` 描述改为 `feishu-api.md / tencent-api.md   # 转写源接口手册 + 爬取失败手动兜底流程`。

- [ ] **Step 5: 文末新增"发布与安装目录同步"节**

```markdown
## 发布与安装目录同步

本仓库即 skill 源；本机 agent 使用前同步到技能目录（排除登录态与运行产物）：

```bash
robocopy "E:\LLMproject\Github\interview-report-kit" "C:\Users\bunny\.agents\skills\interview-report-kit" /MIR /XD .git .auth __pycache__ .pytest_cache .playwright-mcp runs asr_runs /XF "*.pyc"
```

同步后跑 `python <skill>/scripts/doctor.py` 验证。版本：v1.1.0（多源输入 P1+P2）、v1.2.0（+分离转录）。
```

- [ ] **Step 6: 全量验证**

Run: `python -m pytest -q && python scripts/doctor.py && python scripts/extract_text.py --help && python scripts/fetch_tencent.py --help && python scripts/asr_diarize.py --help`
Expected: 测试全 PASS；doctor 正常（funasr 未装仅 ⚠️）；三个新 CLI 帮助正常输出

- [ ] **Step 7: Commit + 打版**

```bash
git add README.md && git commit -m "docs: README 多源化 + 发布同步清单（robocopy 到安装目录）" && git tag v1.2.0
```

---

## Self-Review 结论（已核对）

1. **Spec 覆盖**：场景 1/2/7 走既有环节（不改）；场景 3→Task 11+12；场景 4→Task 3；场景 5→Task 2/4/7 检测；场景 6/7 A2 通道→Task 6+9；契约微扩→Task 2(source_label 生产侧)/4(消费侧)/5(渲染)；命名清理→Task 1；doctor→Task 9；测试→各任务内嵌；分期 v1.1.0→Task 9、v1.2.0→Task 13；发布同步→Task 13。无缺口。
2. **占位符**：无 TBD/TODO；所有代码步骤给出完整代码。
3. **一致性**：`speaker_check.warn_if_no_speakers` 在 Task 2 定义、Task 4/7/11 引用一致；`source_label` 取值（"飞书妙记"/"腾讯会议录制"/"本地文档：…"/"本地录音（FunASR 分离转录）"）与 spec §4 一致；`--rename` Task 4 实现、Task 12 使用；GBK 同步块注释 Task 1 更新后新文件（Task 6/7/11）沿用新文案。
