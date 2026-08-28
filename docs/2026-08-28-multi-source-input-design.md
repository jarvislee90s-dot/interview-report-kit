# 输入端多源兼容设计（interview-report-kit v1.1）

日期：2026-08-28
状态：已与用户逐节确认（brainstorming 产出），待实施
关联：`docs/2026-08-27-interview-report-kit-design.md`（v1.0 设计）

## 1. 背景与目标

v1.0 输入端绑定飞书妙记 URL（必须）+ 本地录音（可选）。实际会议纪要来源远不止妙记，且存在"只有录音"的场景。本次扩展输入端兼容性，覆盖三类输入：

- **A1 网页粗略纪要**（需爬取）：飞书妙记、腾讯会议录制分享页、其他转写网页（通义听悟/钉钉闪记/讯飞听见等，走通用兜底）；
- **A2 本地粗略纪要文档**（无需爬取，直接可用）：md / txt / word / pdf；
- **B 本地录音**。

目标：任何一类输入都能进入现有 ②~⑨ 流水线；输出按需分级（双产物 / 单产物快速）。

非目标（YAGNI）：不做通用网页自动爬虫脚本（低频源走 agent 浏览器复制兜底）；不做 WhisperX/pyannote 路线；不做 HTML 试听标记页；不新增模板样式集。

## 2. 术语与场景矩阵

| 场景 | 输入 | 流程 | 产物 |
|---|---|---|---|
| 1 | 只传 A1 或 A2 | 抓取/提取+结构化 → ②实录 → ⑤润色（跳③④） | 双产物 |
| 2 | (A1 或 A2) + B | ①② ∥ ③ASR → ④交叉校对 → ⑤润色 | 双产物 |
| 3 | 只传 B，要纪要 | `asr_diarize.py` → 对话式标记发言人（此后等价于拿到 A）→ ②⑤（同源**不校对**，无④） | 双产物 |
| 4 | 只传 B，快速 | ③`asr.py` → agent 直接润色+写总结 | 仅 会议总结.html |
| 5 | A1/A2 形式满足但**无发言人信息** | 适配器检测到全员缺发言人 → 响亮警告 → 自动降级走场景 4 | 仅 会议总结.html，完成后提醒用户：补发言人信息才能出访谈纪要 |
| 6 | 其他网页转写（A1 通用兜底） | agent 浏览器复制正文存 txt → 与 A2 同通道（提取+结构化） | 双产物 |
| 7 | 已有规范纪要/总结 md | 直接 ⑧渲染（v1.0 已有能力） | 视 md 类型 |

A1 内部路由：URL 形如 `*.feishu.cn/minutes/*` → `fetch_feishu.py`；`meeting.tencent.com/cw/*` → `fetch_tencent.py`；其余 URL → 场景 6 兜底。仅传 B 时 agent 问用户一句："需要区分发言人出纪要，还是快速出总结？"（场景 3 vs 4）。

## 3. 架构：适配器收口 `minutes_raw.json`

沿用 v1.0 的关键结构事实——`minutes_raw.json`（`paras:[{s,t,x}]`）本就是流水线唯一入口契约，`fetch_minutes.py` 只是它的一个生产者。本次扩展 = 增加生产者，下游 ②~⑨ 基本不动：

```
A1 飞书妙记 URL   → fetch_feishu.py ─┐
A1 腾讯会议 /cw/  → fetch_tencent.py  ├─→ minutes_raw.json ─→ ②build_transcript → ⑤润色 → ⑥总结 → ⑦导图 → ⑧渲染
A1 其他网页 → agent复制存txt ─┐       │
A2 本地文档  → extract_text.py ─→ agent 结构化 → json        │
B + 要纪要  → asr_diarize.py（s=spk:N）→ 对话式标记改名 ────┘
B + 快速    → asr.py → agent 润色+写总结 → ⑦⑧（单产物）
```

职责原则（与用户确认）：**脚本只做确定性的事**（登录、取数、解码、格式提取、机械替换）；**结构识别（发言人/时间戳归属）复杂度高的交给 agent**（LLM 读文本写 json，由 `build_transcript.py` 把关校验）。

## 4. `minutes_raw.json` 契约微扩（向后兼容）

- `t` 允许 `null`/缺省：无时间戳来源（纯文本文档等）。`build_transcript.py` 对无 `t` 段落输出不带时间戳的 `**发言人**` 行；`render.py` 的 `ENTRY_RE` 时间戳改为可选（已验证空值渲染安全、`CHAPTER_TIME` 空串优雅降级；timeline 模板标注"不建议无时间戳来源"）。
- 新增可选 `source_label`（字符串）：如 `"飞书妙记"` / `"腾讯会议录制"` / `"本地文档：xx.docx"` / `"本地录音（FunASR 分离转录）"`。`build_transcript.py` 头部来源行由它驱动（替代写死的"飞书妙记"），有 url 则 `> 来源：{label} {url}`，无则 `> 记录来源：{label}`。
- `total_expected` 保持可选（能确定时填，用于截断校验）。

## 5. 组件设计

### 5.1 `fetch_feishu.py`（由 `fetch_minutes.py` 更名，行为不变 + 无发言人检测）

- 更名原因：`minutes` 字眼来自飞书独占时代，公共命名去歧义（见 §7）。
- 新增：统计空 `s` 段占比；全员为空 → `⚠️ 该来源无发言人信息，将无法生成按发言人组织的纪要（可走快速总结线）`，SKILL.md 场景 5 指引降级。

### 5.2 `fetch_tencent.py`（新）

- 输入：`https://meeting.tencent.com/cw/<code>`（公开分享链接，无需登录；若页面要求访问密码，弹浏览器等用户输入，上限 600s，复用 `.auth` 持久化模式）。
- 实现（复刻 fetch_feishu 的"Playwright 打开页面 → 页面上下文 fetch 接口"模式）。2026-08-28 实测接口链（细节落在 `reference/tencent-api.md`）：
  1. 页面加载后自动完成短码解析（`get-token`、`get-multi-record-info` 得 `uni_record_share_id/meeting_id/recording_id`）；
  2. `GET /wemeet-cloudrecording-webapi/v1/minutes/detail?...&start_pid=0&limit=50` 拉逐字稿，响应 `more:true` 时以末段 `pid` 续拉（guard 防死循环）；
  3. 段落映射（与 json 契约 1:1）：`paragraphs[]` → `{s: speaker.user_name, t: start_time(毫秒), x: sentences[].words[].text 连接}`；过滤空文本；按 `t` 排序；
  4. meta：标题/会议时间从 record-info 接口取。
- 可选 `--with-ai-summary`（默认开）：调 `query-summary-and-note` 抓腾讯 AI 纪要存 `tencent_ai_summary.md`（供 ⑥ 参考，失败不阻塞）。
- 无发言人检测（同 5.1）；响亮失败：接口异常 / 零段落 / 分页 guard 触发 → 提示按 `reference/tencent-api.md` 手动兜底。

### 5.3 `extract_text.py`（新，A2 通道）

- 输入：本地 md/txt（utf-8→gbk 解码探测链）、docx（python-docx 段落提取）、pdf（pypdf 文本提取，按页序拼接）。
- 输出：`<名称>.extracted.txt`（纯文本 utf-8）+ 行数/字数统计。
- **零启发式结构识别**——发言人/时间戳结构判定交给 agent（下一环）。
- 响亮失败：解码失败、docx/pdf 损坏（提示重存/转存）。
- `python-docx`、`pypdf` 进主 `requirements.txt`（轻量）。

### 5.4 agent 结构化环节（新，SKILL.md + pipeline.md 细则）

- 输入：`.extracted.txt`（或场景 6 的网页复制文本）。
- agent 忠实转录为 `minutes_raw.json`：`{source_label, total_expected?, paras:[{s?, t?(毫秒), x}]}`。**只转录不润色**（润色是 ⑤ 的事）；识别不出发言人时 `s` 留空（走场景 5 判定：全员空 → 降级）。
- 把关：跑 `build_transcript.py` 转换（缺 paras/结构错即拒绝），产出 `会议实录.md` 后进入 ⑤。

### 5.5 `asr_diarize.py`（新，场景 3）

- 引擎：FunASR `AutoModel(model="paraformer-zh", vad_model="fsmn-vad", punc_model="ct-punc", spk_model="cam++")`，`generate()` 一次输出转写+说话人标签+句级时间戳。
- 产物：`asr_runs/<名称>/diarize_raw.json`（FunASR 原始）+ `minutes_raw.json`（`s="spk:0/1/2..."`，`t=句首毫秒`；相邻同 spk 句合并为段，超约 500 字切段）。
- 结束打印每号声音的首/中/末各 1 句样例（供对话式标记直接引用）。
- 模型从 ModelScope 自动下载（国内网络友好，无需 HF 授权）；device 自动。依赖单独放 `requirements-diarize.txt`（funasr、torch 等重依赖，不进默认安装）。

### 5.6 对话式标记发言人（场景 3 落地，零新脚本）

- agent 在对话中列出各 `spk:N` 及样例句 → 用户回复映射（如"spk:0 是张三，spk:1 是主持人"）→ agent 组装：
  `python <skill>/scripts/build_transcript.py minutes_raw.json --rename "spk:0=张三,spk:1=主持人" --out 会议实录.md`
- `build_transcript.py` 新增 `--rename`（json 读入后按 映射改写 `s`；未映射者保留原标签并 ⚠️ 提示）。

### 5.7 `build_transcript.py`（扩展）

- `--rename`（见 5.6）；`source_label` 来源行（§4）；`t` 缺省段落输出无时间戳行；全员无发言人警告（场景 5）。

### 5.8 `render.py`（微调）

- `ENTRY_RE` 时间戳改可选：`^\*\*(.+?)\*\*(?: ([\d: /–\-—]+))?$`；`ts` 空串渲染为空（模板无需改）。
- SKILL.md 注明：无时间戳来源不建议选 timeline 模板。

### 5.9 场景 4 快速线（零新脚本）

- `asr.py`（现有）→ agent 按 pipeline.md 新增"快速总结原则"直接写 `会议总结.md`（头部 meta 注明"来源：本地录音 faster-whisper 转录（快速模式，未经发言人区分）"；不产出实录/纪要，不做④⑤逐段润色；模糊片段标注原则保留）→ ⑦ 思维导图（默认生成；用户明确要求"最快"时省略）→ ⑧ 只渲染 summary 版式。
- 产物树无 `访谈纪要.html` / `会议实录（修正）.md` / `corrections.json`。

### 5.10 `doctor.py`（增项）

- `python:docx`、`python:pypdf`（缺失标 ❌，仅 A2 路径需要，注释说明）；`python:funasr`（缺失标 ⚠️ 可选，仅场景 3 需要）。

## 6. SKILL.md 改版

- frontmatter `description` 重写：触发条件覆盖"妙记/腾讯会议/其他转写网页链接、本地纪要文档、本地录音"等表述（当前写死"飞书妙记 URL（必须）"会挡住其他触发）。
- §1 定位改为来源无关表述；§3 工作流头部插入 **"第 0 环节：输入路由"**（§2 场景矩阵 + A1 内部 URL 路由规则 + 场景 3/4 一问分流 + 场景 5 降级与提醒话术）。
- §4 产物结构按场景标注差异；§5/§6 补 `fetch_tencent.py` 兜底指引（`reference/tencent-api.md`）。

## 7. 命名清理

- `fetch_minutes.py` → **`fetch_feishu.py`**（飞书专用却占了通用名）。
- `minutes_raw.json` **保留**：语义是"原始纪要数据"，本就来源无关；改名会连带 SKILL.md/README/示例/测试大面积 churn。
- 全库扫"minutes/妙记"字眼，公共文案（SKILL.md 定位、来源行、README）改来源无关表述；飞书/腾讯专属文档（`reference/feishu-api.md`、新增 `reference/tencent-api.md`）保持专属命名。

## 8. 错误处理与兜底（沿用"响亮失败 + 手册兜底"原则）

| 组件 | 失败情形 | 处理 |
|---|---|---|
| fetch_feishu | 接口异常、零段落、段数 <90%（total_expected 基准） | exit 1 + 指引 `reference/feishu-api.md` agent 浏览器手动兜底 |
| fetch_tencent | 接口异常、零段落、分页 guard 触发（接口无总段数，完整性由 `more:false` 正常收敛保证） | exit 1 + 指引 `reference/tencent-api.md` agent 浏览器手动兜底 |
| 两个 fetcher | 全员无发言人 | ⚠️ 警告 + SKILL.md 场景 5 降级（走快速线，完成后提醒补发言人可出纪要） |
| extract_text | 解码/格式损坏 | exit 1 + 提示重存/转存 |
| agent 结构化 | json 结构错/缺 paras | `build_transcript.py` 拒绝转换，agent 修正重跑 |
| asr_diarize | 依赖缺失/模型下载失败 | 指引 `pip install -r requirements-diarize.txt`；hf-mirror 式重试不适用（ModelScope 直连国内友好） |

## 9. 测试策略

- `test_fetch_tencent_parse.py`：纯解析函数——接口响应 fixture → paras 映射、分页拼接（`more:true`/`pid` 游标）、空段过滤、无发言人检测。Playwright 壳不自动测（与现状一致）。
- `test_build_transcript.py`：`--rename` 映射与未映射警告；`t` 缺省输出；`source_label` 来源行；缺 paras 拒绝。
- `test_render.py` 增补：无时间戳 entry 渲染（空 chip 不崩）；含 `spk:0` 名字的发言人配色正常。
- `test_extract_text.py`：utf-8/gbk 探测；docx 临时生成 fixture 提取；损坏文件 exit 1。
- `test_asr_diarize.py`：句级结果 → paras 合并纯函数（同 spk 相邻合并、500 字切段）。模型装载不测。
- 全部沿用现有 pytest + fixtures 模式（`tests/fixtures/`）。

## 10. 分期实施

- **Phase 1（轻）**：场景 4 快速线（SKILL.md 路由 + pipeline.md 快速总结原则）+ 命名清理（`fetch_feishu.py` 更名及全库文案）。
- **Phase 2（中）**：A1 腾讯 + A2 本地文档——`fetch_tencent.py`、`extract_text.py`、agent 结构化细则、`build_transcript.py` 扩展（source_label / t 可缺省 / --rename 一并实现）、`render.py` ENTRY_RE 微调、`reference/tencent-api.md`、doctor 增项、测试。
- **Phase 3（重）**：场景 3——`asr_diarize.py`、`requirements-diarize.txt`、对话式标记工作流、doctor funasr 检查、测试。

每期独立可交付、可发版。

## 11. 发布与同步

- README 发布清单新增：同步到本机安装目录 `C:\Users\bunny\.agents\skills\interview-report-kit`（robocopy 一行命令；`.auth` 目录排除）。
- 语义化版本：v1.1.0（Phase 1+2）、v1.2.0（Phase 3）。

## 12. 关键决策记录

| 决策 | 结论 | 理由 |
|---|---|---|
| 收口架构 | 多生产者 → `minutes_raw.json` 一契约 | 顺 v1.0 架构，下游零改动，适配器独立可测 |
| 腾讯取数 | 页面上下文调 `minutes/detail` 接口（非 DOM 解析） | 接口稳定、分页干净、与 json 契约 1:1（2026-08-28 实测） |
| 结构识别 | agent（LLM）判定，脚本零启发式 | 文档格式发散，正则阈值不可靠；json 由 build_transcript 把关 |
| 说话人分离 | FunASR（paraformer-zh + cam++） | 中文优化、一次调用出全量结果、免 HF 授权、CPU 可跑；WhisperX 需 HF 授权且中文偏弱 |
| 人工标记 | 对话式 + `--rename` 参数落地 | 零新 UI，符合 agent 工作流 |
| (c) 快速线 | 零新脚本，纯工作流分支 | `asr.py` + 渲染引擎已具备全部能力 |
