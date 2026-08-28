---
name: interview-report-kit
description: "会议/访谈实录→纪要/总结 HTML 报告套件。触发条件：用户提供会议转写链接（飞书妙记、腾讯会议录制分享）或本地纪要文档（md/txt/word/pdf）或本地录音，要求生成访谈纪要、会议总结、网页版报告；或说'整理访谈实录''生成访谈纪要HTML'；或仅提供访谈/纪要 markdown 要求套模板渲染 HTML。"
---

# interview-report-kit

## 1. 定位

输入（详见第 0 环节输入路由）：**粗略纪要来源**（A1 网页类——飞书妙记 URL、腾讯会议录制分享、其他转写网页；A2 本地文档——md/txt/word/pdf）和/或**本地录音**（B——可分发言人转录，或快速总结）。
输出：**中间 markdown**（原始实录 → 修正实录 → 会议总结）+ **两份自包含 HTML 报告**：

- 访谈纪要.html —— 按发言人时间块组织的全文纪要
- 会议总结.html —— 分主题要点总结（可内嵌思维导图）

HTML 由 `reference/templates/` 下 **5 套模板** 承载样式：`research-report`（调研报告）/ `clean-doc`（简洁文档）/ `modern-card`（卡片）/ `chat-bubble`（对话气泡）/ `timeline`（时间线），每套均含 `minutes`（纪要）与 `summary`（总结）两个版式。

流程 = 6 个脚本环节（爬取→转 md→本地 ASR→机械校正→渲染）+ 3 个 LLM 环节（逐段比对校正→润色→写总结/思维导图）。LLM 环节的操作细则见 `reference/pipeline.md`（必读）。

## 2. 环境前置

```bash
pip install -r <skill>/requirements.txt
playwright install chromium
```

另需系统依赖：**ffmpeg**（`winget install Gyan.FFmpeg` 或 `brew install ffmpeg`）、**Node + mmdc**（`npm i -g @mermaid-js/mermaid-cli`，渲染思维导图用）。

自检（全部 ✅ 才继续）：

```bash
python <skill>/scripts/doctor.py
```

检查项：ffmpeg、node、mmdc(mermaid-cli)、python:playwright、python:faster_whisper。（确定不提供音频时，faster_whisper 缺失不影响除 ③④ 外的环节，但 doctor 仍会报 ❌。）

> 约定：下文 `<skill>` 指本 skill 根目录（本文件所在目录）；其余相对路径（`minutes_raw.json`、`会议实录.md` 等）均相对**项目工作目录**——先 `cd` 到项目目录再执行。

## 3. 工作流（⓪~⑨ 环节）

### ⓪ 输入路由（先判断走哪条线）

| 输入形态 | 入口 | 输出 |
|---|---|---|
| 飞书妙记 URL（`*.feishu.cn/minutes/*`） | ① `fetch_feishu.py` | 双产物 |
| 腾讯会议录制分享（`meeting.tencent.com/cw/*`） | ①′ `fetch_tencent.py` | 双产物 |
| 其他转写网页 | agent 浏览器复制正文存 txt → `extract_text.py` 同 A2 通道 | 双产物 |
| 本地纪要文档（md/txt/word/pdf） | `extract_text.py` + agent 结构化（①″） | 双产物 |
| 仅本地录音 + 要区分发言人 | `asr_diarize.py` + 对话式标记（Phase 3 交付） | 双产物 |
| 仅本地录音 + 快速 | ③ `asr.py` → 快速总结线（见 ⑨ 后） | 仅 会议总结.html |
| 已有规范纪要/总结 md | 直接 ⑧ | 视 md 类型 |

- 纪要来源 + 本地录音同传 → ③④ 交叉校对线（双产物）。
- 抓取后发现**全员无发言人**（环节 ①~② 会警告）→ 降级快速总结线，完成后提醒用户：补发言人信息才能出访谈纪要.html。
- 仅录音时先问用户："需要区分发言人出纪要，还是快速出总结？"

### ① 抓取妙记 → minutes_raw.json

```bash
python <skill>/scripts/fetch_feishu.py "<妙记URL>"
```

- URL 形如 `https://xxx.feishu.cn/minutes/<token>`；可选 `--auth-dir`（默认 `<skill>/.auth`）、`--out`（默认 `minutes_raw.json`）。
- 首次运行弹出浏览器，**扫码登录飞书**（等待上限 600 秒）；登录态持久存于 `.auth`，之后免登。
- 预期输出：`✅ 抓取完成：N 段 / M 人 / 末段 M:SS → minutes_raw.json`。
- 产物结构：`{"url","title","meeting_time","total_expected","paras":[{"s":发言人,"t":毫秒,"x":文本},...]}`。
- **响亮失败**（提示按 `reference/feishu-api.md` 手动兜底）：页面上下文抓取异常、零段落、或段数不足 `total_expected` 的 **90%**。

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

### ② 原始实录 → 会议实录.md

```bash
python <skill>/scripts/build_transcript.py minutes_raw.json --out 会议实录.md
```

- 预期输出：`written: 会议实录.md（N 段 / M 人）`；若段数与 `total_expected` 不符会打印截断警告（⚠️ 需回①重抓）。
- 产物：头部 meta（来源/会议时间/发言人清单）+ `---` + 逐段 `**发言人** HH:MM:SS` 段落。
- 可选 `--url` 覆盖 json 内 url。

### ③ 本地音频转录（可选，无音频跳过③④）

```bash
python <skill>/scripts/asr.py <音频/视频文件> --outdir asr_runs/<名称>
```

- 可选 `--model large-v3-turbo`、`--language zh`。
- 流程：ffmpeg 提取 16k 单声道 wav → faster-whisper 转录；产物 `transcript.txt` / `transcript.json`（及 `audio.wav`）。
- **CPU 转录约 1.2× 音频时长**（1 小时音频 ≈ 72 分钟）——建议后台运行，并与 ①② 并行。
- 模型下载失败自动切换 hf-mirror 重跑；产物已存在则跳过（**断点续跑**，中断后原命令重跑即可）。

### ④ 双源比对 → corrections.json → 会议实录（修正）.md

Agent 读 `会议实录.md` 与 `transcript.txt` **逐段比对**，按 `reference/pipeline.md` 的校正原则写 `corrections.json`，然后：

```bash
python <skill>/scripts/apply_corrections.py 会议实录.md corrections.json --out 会议实录（修正）.md
```

- 规则格式：`[{"old":"原文","new":"修正","expect":1,"basis":"依据"},...]`（`expect` 缺省 1，**必须整数** = 实测命中数）。
- **硬校验**：规则**按序应用**（第 i 条在前 i-1 条应用后的文本上计数替换）；任何一条命中数 ≠ expect 即**全量拒绝、不写任何文件**；输出段落数必须与输入一致。
- 预期输出：`✅ applied N 条 → 会议实录（修正）.md（段落数 M 不变）`。

### ⑤ 润色（就地改写 会议实录（修正）.md）

Agent 按 `reference/pipeline.md` 润色原则**就地改写** `会议实录（修正）.md`：合并同一发言人连续发言为时间块、口语书面化、逻辑分段、按议题分 `##` 章节（标题带时间范围）。无音频跳过③④时，本环节直接润色 `会议实录.md`。

### ⑥ 会议总结.md

Agent 按 `reference/pipeline.md` 总结结构写 `会议总结.md`：头部 meta 行（`> ` 格式）+ 概览 + 按主题 `##` 分节 + 要点列表 + 引用块点睛 + 后续跟进。**总结正文分节用 `##`；首行 `# 标题` 由渲染承接**（模板取其作 TITLE，正文 h1 自动隐藏）。

### ⑦ 思维导图

Agent 按 `reference/pipeline.md` 写 `思维导图.mmd`（mermaid mindmap），然后：

```bash
mmdc -i 思维导图.mmd -o 思维导图.png -w 1600 -b white
```

mmdc 失败的兜底见 pipeline.md（不传 `--mindmap`，仅嵌源码）。

### ⑧ 渲染 HTML

```bash
python <skill>/scripts/render.py --list-templates
python <skill>/scripts/render.py 会议实录（修正）.md --template research-report/minutes --out 访谈纪要.html
python <skill>/scripts/render.py 会议总结.md --template research-report/summary --mindmap 思维导图.png --out 会议总结.html
```

- 模板共 5 set（`chat-bubble` / `clean-doc` / `modern-card` / `research-report` / `timeline`）× 2 版式（minutes/summary）；**纪要与总结建议同 set**。
- `--mindmap` 把 png base64 内嵌进页面（触发模板 `IF:MINDMAP` 块；不传则该块自动隐藏）。`--mindmap` 仅 summary 版式支持（模板含导图承接块）；minutes 版式传 `--mindmap` 会报错。
- 可选 `--title` / `--kicker` / `--source-url` / `--out`（缺省 `<md>.html`；禁止与输入同文件）。
- 头部信息自动从 md meta 行读取：`> 来源：`（→SOURCE_URL）、`> 会议时间：2026-03-10 09:06 · 时长 1:06:24 · …`（→DATE/DURATION）。发言人两形态：原始版头部 `> 发言人 8 人：A、B…` 不匹配 meta 正则，SPEAKERS_LINE 由引擎按实录发言人自动重组；润色版/总结版建议写 `> 发言人：名字、名字`（全角冒号紧跟"发言人"，此形态才会进 SPEAKERS_LINE）。
- 发言人配色自动按出现顺序分配；模板内 `<!--COLORS: 名=#hex,…-->` 注释可预设发言人配色。
- 预期输出：`✅ <set>/<doc> ← <md名> → <out>（N KB）`。

### ⑨ 验证（可选）

```bash
python -m http.server 8000
```

浏览器抽查 `http://localhost:8000/访谈纪要.html` 与 `http://localhost:8000/会议总结.html`（章节导航、发言人配色、思维导图、打印预览）。

### 快速总结线（仅录音 · 单产物，跳过 ①②④⑤）

1. `python <skill>/scripts/asr.py <音频/视频文件> --outdir asr_runs/<名称>`（同 ③）。
2. Agent 读 `transcript.txt`，按 `reference/pipeline.md` §6 快速总结原则直接写 `会议总结.md`（meta 注明"来源：本地录音 faster-whisper 转录（快速模式，未经发言人区分）"）。
3. ⑦ 思维导图（默认生成；用户明确要求"最快"时省略）→ ⑧ 仅渲染 summary 版式。

产物：`会议总结.md` + `会议总结.html`（无 访谈纪要.html / 会议实录（修正）.md / corrections.json）。

## 4. 产物结构

```text
<项目目录>/
├── minutes_raw.json               # ① 妙记原始数据（url/title/meeting_time/total_expected/paras）
├── tencent_ai_summary.json        # ①′ 腾讯 AI 纪要参考（仅腾讯源，可选）
├── <名>.extracted.txt             # ①″ 本地文档提取的纯文本（A2 通道中间产物）
├── 会议实录.md                     # ② 原始实录（未经校对）
├── asr_runs/<名称>/               # ③ 本地转录（audio.wav / transcript.txt / transcript.json）
├── corrections.json               # ④ 校正规则（agent 生成，含 expect/basis，可审计）
├── 会议实录（修正）.md              # ④⑤ 校正+润色后的终版实录（渲染纪要的源）
├── 会议总结.md                     # ⑥ 总结源稿（渲染总结的源）
├── 思维导图.mmd / 思维导图.png      # ⑦ mermaid 源码 + 渲染图
├── 访谈纪要.html                   # ⑧ 纪要网页（自包含，可直接分发）
└── 会议总结.html                   # ⑧ 总结网页（自包含，含内嵌思维导图）
```

## 5. 注意事项

- **md 是唯一事实源**：所有中间 md 随时可手动编辑，改完**重跑 ⑧** 即可重新出 HTML；不要手改 HTML。
- `render.py` 是独立 CLI，可脱离流水线给**任意 markdown** 套模板：纪要版式要求 `**发言人** 时间` 块与 `## 章节` 结构，summary 版式只需普通 md（`{{BODY}}` 承接）。
- **自定义模板**：复制 `reference/templates/<set>/` 目录改样式即成新模板，改完用 `python <skill>/scripts/doctor.py --check-template reference/templates/<新set>/minutes.html` 校验占位符契约。注意两点：
  - 模板中 `<!-- 复制模板时改：日期 -->2026-XX-XX`、`<!-- 复制模板时改：品牌名 -->` 等标记处需替换为实际值（HTML 注释，不影响渲染，但漏改会原样出现在页面里）。
  - `<!--COLORS: 名=#hex,…-->` 注释可预设发言人配色：名字须与实录发言人**完全一致**（含前缀/空格），未列出者按引擎调色板顺序自动配色；该注释渲染时自动剔除。
- **并行**：③ ASR 慢，可与 ①② 同时启动（ASR 只需要音频文件，不需要妙记数据）。
- 登录态存于 `<skill>/.auth`（已 gitignore）；换机器或目录损坏时删除后重跑 ① 重新扫码。
- Windows 下脚本对 GBK 控制台已做容错；文件均为 UTF-8。

## 6. 手动兜底

`fetch_feishu.py` 失败（接口字段变化、登录异常、段数 <90%）时，按 **`reference/feishu-api.md`** 用 agent 浏览器（MCP）在页面上下文手动调妙记接口补齐 `minutes_raw.json`，然后从 ② 继续。

`fetch_tencent.py` 失败（未捕获逐字稿请求 / 零段落 / 分页异常）时，按 **`reference/tencent-api.md`** 用 agent 浏览器在页面上下文手动分页取数补齐 `minutes_raw.json`，然后从 ② 继续。
