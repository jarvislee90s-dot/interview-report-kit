# 输入端多源兼容设计（interview-report-kit v1.1）

日期：2026-08-28
状态：已与用户逐节确认（brainstorming 产出），待实施
关联：`docs/2026-08-27-interview-report-kit-design.md`（v1.0 设计）

> 本文是产品级说明书：描述"做什么、怎么运转、失败时如何表现"。接口调用链、正则表达式、模型构造参数、测试用例清单等实现细节见实施 plan（腾讯接口实测细节另随 Phase 2 落入 `reference/tencent-api.md`）。

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

## 3. 总体架构：多生产者，一个契约

v1.0 的关键结构事实是：`minutes_raw.json`（段落数组 `paras:[{s,t,x}]`——发言人、毫秒时间戳、正文）本就是整条流水线的唯一入口契约，`fetch_minutes.py` 只是它的一个生产者。本次扩展就是**给它增加更多生产者**，下游 ②~⑨ 环节基本不动：

```
A1 飞书妙记 URL    → fetch_feishu.py ─┐
A1 腾讯会议 /cw/   → fetch_tencent.py  ├─→ minutes_raw.json ─→ ②build_transcript → ⑤润色 → ⑥总结 → ⑦导图 → ⑧渲染
A1 其他网页 → agent 复制存 txt ─┐      │
A2 本地文档  → extract_text.py ──→ agent 结构化 → json        │
B + 要纪要  → asr_diarize.py（s=spk:N）→ 对话式标记改名 ─────┘
B + 快速    → asr.py → agent 润色+写总结 → ⑦⑧（单产物）
```

职责划分原则（与用户确认）：**脚本只做确定性的事**——登录、取数、解码、格式提取、机械替换；**结构识别（发言人/时间戳归属）复杂度高的交给 agent**（LLM 读文本写 json，再由 `build_transcript.py` 把关校验）。

## 4. 数据契约：`minutes_raw.json` 微扩（向后兼容）

- **`t` 允许缺省**：无时间戳来源（纯文本文档等）。`build_transcript.py` 对无 `t` 段落输出不带时间戳的发言块；`render.py` 的纪要版式（`ENTRY_RE`）相应把时间戳改为可选。已验证空时间戳在现有模板下安全降级；timeline 模板标注"不建议无时间戳来源"。
- **新增可选 `source_label`**：来源的展示名，如 `"飞书妙记"` / `"腾讯会议录制"` / `"本地文档：xx.docx"` / `"本地录音（FunASR 分离转录）"`。`build_transcript.py` 头部来源行由它驱动（替代现在写死的"飞书妙记"）。
- **`total_expected` 保持可选**：适配器能确定总段数时填，用于截断校验。

## 5. 组件说明

每个组件按"输入 → 输出 → 职责要点 → 失败时表现"描述。

### 5.1 `fetch_feishu.py`（由 `fetch_minutes.py` 更名）

- 输入/输出：妙记 URL → `minutes_raw.json`，行为与 v1.0 一致。
- 新增能力：无发言人检测——全员缺发言人名时给出响亮警告并提示降级路径（场景 5）。

### 5.2 `fetch_tencent.py`（新，A1·腾讯会议）

- 输入/输出：腾讯会议录制分享链接（`/cw/<code>`）→ `minutes_raw.json`。
- 运转方式：公开分享链接无需登录即可查看；脚本复刻 `fetch_feishu.py` 的"浏览器打开页面 → 页面上下文取数"模式，从逐字稿接口分页拉取（预研 2026-08-28 实测：接口字段与 `paras` 契约一一对应——发言人名、毫秒时间戳、正文；链接若带访问密码则弹浏览器等用户输入）。
- 附加能力：可顺带抓取腾讯自带的 AI 纪要存为参考文件（供 ⑥ 总结环节参考，失败不阻塞）；无发言人检测（同 5.1）。
- 失败时表现：接口异常、零段落、分页异常终止 → 响亮失败，指引 `reference/tencent-api.md` 手动兜底。

### 5.3 `extract_text.py`（新，A2·本地文档）

- 输入/输出：本地 md / txt / word / pdf → 纯文本文件（UTF-8），附行数字数统计。
- 运转方式：负责编码探测与文档格式提取（word/pdf 按文档结构取文本）。**不做任何发言人/时间戳结构识别**——那是不确定性的判断，交给下一环 agent。
- 失败时表现：解码失败、文档损坏 → 响亮失败，提示重存/转存。

### 5.4 agent 结构化（新环节，细则入 SKILL.md / pipeline.md）

- 输入/输出：`.extracted.txt`（或场景 6 的网页复制文本）→ `minutes_raw.json`。
- 运转方式：agent **忠实转录**为 `paras`（识别不出发言人时 `s` 留空，触发场景 5 判定）；只转录不润色（润色是 ⑤ 的事，纪律同 v1.0）。
- 把关：产物必须过 `build_transcript.py` 转换（结构错即拒绝），成功产出 `会议实录.md` 后进入 ⑤。

### 5.5 `asr_diarize.py`（新，场景 3·录音分离转录）

- 输入/输出：本地音视频 → `minutes_raw.json`（发言人暂为匿名标签 `spk:0/1/2...`）+ FunASR 原始结果留档。
- 运转方式：FunASR（paraformer-zh 语音识别 + cam++ 说话人分离）一次调用同时产出转写、说话人标签、句级时间戳；同人相邻句子合并为段落、过长自动切分。模型从 ModelScope 自动下载（国内网络友好，无需 HuggingFace 授权）。
- 附加能力：结束时打印每号声音的首/中/末样例句，供对话式标记直接引用。
- 失败时表现：依赖缺失 → 指引安装 `requirements-diarize.txt`（重依赖不进默认安装）。

### 5.6 对话式标记发言人（场景 3 落地，零新脚本）

- 运转方式：agent 在对话中列出各 `spk:N` 及样例句 → 用户回复映射（如"spk:0 是张三，spk:1 是主持人"）→ agent 以 `build_transcript.py --rename "spk:0=张三,..."` 一步落名。未映射的标签保留原名并提示。

### 5.7 `build_transcript.py`（扩展）

- `--rename` 说话人改名（5.6）；`source_label` 驱动来源行（§4）；无 `t` 段落输出无时间戳行；全员无发言人警告（场景 5）。

### 5.8 `render.py`（微调）

- 纪要版式入口正则（`ENTRY_RE`）时间戳改为可选；模板无需改动。其余不动。

### 5.9 场景 4 快速线（零新脚本）

- 运转方式：`asr.py`（现有）→ agent 按 pipeline.md 新增"快速总结原则"直接写 `会议总结.md`（头部 meta 注明"来源：本地录音 faster-whisper 转录（快速模式，未经发言人区分）"；不产出实录/纪要，不做④⑤逐段润色；模糊片段标注原则保留）→ ⑦ 思维导图（默认生成；用户明确要求"最快"时省略）→ ⑧ 只渲染 summary 版式。
- 产物树无 `访谈纪要.html` / `会议实录（修正）.md` / `corrections.json`。

### 5.10 `doctor.py`（增项）

- 自检新增：word/pdf 提取依赖（缺失标 ❌，仅 A2 路径需要）；funasr（缺失标 ⚠️ 可选，仅场景 3 需要）。

## 6. SKILL.md 改版（产品主手册）

- frontmatter `description` 重写：触发条件覆盖"妙记/腾讯会议/其他转写网页链接、本地纪要文档、本地录音"等表述（当前写死"飞书妙记 URL（必须）"会挡住其他触发）。
- §1 定位改为来源无关表述；§3 工作流头部插入 **"第 0 环节：输入路由"**（§2 场景矩阵 + A1 内部 URL 路由规则 + 场景 3/4 一问分流 + 场景 5 降级与提醒话术）。
- §4 产物结构按场景标注差异；§5/§6 补 `fetch_tencent.py` 兜底指引（`reference/tencent-api.md`）。

## 7. 命名约定

- `fetch_minutes.py` → **`fetch_feishu.py`**（飞书专用却占了通用名，"minutes"字眼来自飞书独占时代）。
- `minutes_raw.json` **保留**：语义是"原始纪要数据"，本就来源无关；改名会连带 SKILL.md/README/示例/测试大面积 churn。
- 全库扫"minutes/妙记"字眼，公共文案（SKILL.md 定位、来源行、README）改来源无关表述；飞书/腾讯专属文档（`reference/feishu-api.md`、新增 `reference/tencent-api.md`）保持专属命名。

## 8. 失败与兜底原则

沿用 v1.0 "响亮失败 + 手册兜底"原则，所有新组件遵守同一条纪律：**失败即大声退出并指明下一步**，不静默降级。具体判定阈值与判定位置在 plan 中细化，原则如下：

- 网页适配器（飞书/腾讯）：接口异常、零段落、取数不完整 → 退出并指引对应 `reference/*-api.md` 用 agent 浏览器手动兜底；
- 全员无发言人（两个 fetcher 与 agent 结构化环节均检测）→ 警告并按场景 5 降级；
- 文档提取失败 → 退出并提示重存/转存；
- agent 结构化产物 → 由 `build_transcript.py` 把关，结构错即拒绝；
- 分离转录依赖缺失 → 指引安装 `requirements-diarize.txt`。

## 9. 质量与测试

- 每个新脚本把"纯逻辑部分"（解析、映射、合并、改名）独立成可单测函数，配套 pytest 单测；Playwright 壳与模型装载不做自动化测试（与 v1.0 现状一致）。
- 用例清单与 fixture 设计（腾讯接口响应、各格式文档、rename/无时间戳渲染等）在 plan 中列出。

## 10. 分期路线

- **Phase 1（轻）**：场景 4 快速线（SKILL.md 路由 + pipeline.md 快速总结原则）+ 命名清理（`fetch_feishu.py` 更名及全库文案）。
- **Phase 2（中）**：A1 腾讯 + A2 本地文档——`fetch_tencent.py`、`extract_text.py`、agent 结构化细则、`build_transcript.py` 扩展（source_label / t 可缺省 / --rename 一并实现）、`render.py` 微调、`reference/tencent-api.md`、doctor 增项、测试。
- **Phase 3（重）**：场景 3——`asr_diarize.py`、`requirements-diarize.txt`、对话式标记工作流、doctor funasr 检查、测试。

每期独立可交付、可发版。

## 11. 发布与同步

- README 发布清单新增：同步到本机安装目录 `C:\Users\bunny\.agents\skills\interview-report-kit`（一行复制命令；`.auth` 目录排除）。
- 语义化版本：v1.1.0（Phase 1+2）、v1.2.0（Phase 3）。

## 12. 关键决策记录

| 决策 | 结论 | 理由 |
|---|---|---|
| 收口架构 | 多生产者 → `minutes_raw.json` 一契约 | 顺 v1.0 架构，下游零改动，适配器独立可测 |
| 腾讯取数 | 页面上下文调逐字稿接口（非 DOM 解析） | 接口稳定、分页干净、与 json 契约 1:1（2026-08-28 实测） |
| 结构识别 | agent（LLM）判定，脚本零启发式 | 文档格式发散，正则阈值不可靠；json 由 build_transcript 把关 |
| 说话人分离 | FunASR（paraformer-zh + cam++） | 中文优化、一次调用出全量结果、免 HF 授权、CPU 可跑；WhisperX 需 HF 授权且中文偏弱 |
| 人工标记 | 对话式 + `--rename` 参数落地 | 零新 UI，符合 agent 工作流 |
| 快速线 | 零新脚本，纯工作流分支 | `asr.py` + 渲染引擎已具备全部能力 |
