# interview-report-kit 设计文档

日期：2026-03-10
状态：设计已获用户批准（含两轮澄清），待实施

## 1. 背景与目标

2026-03-10 OceanDemo 路演访谈项目中踩通了一条完整流水线：飞书妙记云端实录爬取 → 本地音频 ASR → 双源交叉校正 → LLM 润色 → 会议总结 → Mermaid 思维导图 → 研报风 HTML。本 skill 将该流程沉淀为可复用工具。

**一句话定位**：拿到飞书妙记 URL（+可选本地音频），产出一套可编辑的中间 markdown 和最终的 访谈纪要 HTML + 会议总结 HTML（模板可一键切换）。

**硬约束**：完全自包含——所有脚本、模板、文档沉淀在 skill 文件夹内，不引用任何外部 skill 的文件；他人拷走整个文件夹即可开箱使用。

## 2. 输入输出

```
输入：妙记 URL（必须） + 本地音频文件（可选，无则跳过 ASR 与交叉校正）
输出：<工作目录>/
├── minutes_raw.json          # ①爬取的原始结构化实录
├── 会议实录.md               # ②逐段原始实录（发言人+时间戳）
├── transcript.txt/json       # ③ASR 转录（有音频时）
├── corrections.json          # ④Agent 生成的校正规则（可审计）
├── 会议实录（修正）.md        # ④校正版 → ⑤润色版（同一文件递进，保持可编辑）
├── 会议总结.md               # ⑥
├── 思维导图.mmd / .png       # ⑦
├── 访谈纪要.html             # ⑧（模板任选）
└── 会议总结.html             # ⑧（模板任选）
```

## 3. 目录结构（自包含）

```
C:\Users\bunny\.agents\skills\interview-report-kit\
├── SKILL.md                      # 全流程主指引 + 失败兜底
├── requirements.txt              # playwright、faster-whisper（ffmpeg/mmdc/node 为系统依赖）
├── scripts/
│   ├── doctor.py                 # 环境自检 + --check-template 模板占位符校验
│   ├── fetch_minutes.py          # ①妙记爬取
│   ├── build_transcript.py       # ②json→会议实录.md
│   ├── asr.py                    # ③音频→transcript（自带逻辑，不依赖 video-summary）
│   ├── apply_corrections.py      # ④校正执行器
│   └── render.py                 # ⑧md+模板→HTML（独立 CLI）
└── reference/
    ├── templates/                # 模板库：5 个 set × 2 = 10 个自包含模板
    │   ├── research-report/{minutes,summary}.html
    │   ├── clean-doc/{minutes,summary}.html
    │   ├── modern-card/{minutes,summary}.html
    │   ├── chat-bubble/{minutes,summary}.html
    │   └── timeline/{minutes,summary}.html
    ├── pipeline.md               # LLM 环节操作细则
    └── feishu-api.md             # 妙记 API 手册 + 手动兜底流程
```

## 4. 模板库（核心设计）

**set 定义**：同一 UI 风格家族；`minutes.html`（章节+发言块结构）与 `summary.html`（纯文档结构）内部结构不同、视觉语言一致。

**5 个 set（第一版）**：

| set | 风格 | 来源 | 特征 |
| --- | --- | --- | --- |
| research-report | 研报风 | 本次终版抽取 | 藏青#1B2A4A+鎏金#a8842c、米纸底、衬线标题、左侧粘性目录、筛选/搜索交互 |
| clean-doc | 简洁文档 | 本次总结网页版抽取+补齐纪要 | 纯文档零 JS、打印最优 |
| modern-card | 现代卡片 | 本次初版复拓 | 亮色、彩色头像图例、圆角卡片、hover 阴影 |
| chat-bubble | 对话气泡 | 新设计 | IM 聊天样式：圆头像+按发言人着色的左右气泡 |
| timeline | 时间轴 | 新设计 | 垂直时间轴串联发言块，时间戳在轴上 |

**模板规范**（自包含完整 HTML，纯字符串占位，零模板引擎）：

- 单值占位：`{{TITLE}} {{KICKER}} {{DATE}} {{DURATION}} {{SPEAKERS_LINE}} {{SOURCE_URL}} {{MINDMAP_B64}}`
- 条件块：`<!--IF:MINDMAP-->…<!--/IF:MINDMAP-->`（无导图时整段移除）
- 可重复块（结构留在模板，脚本只填充）：
  ```html
  <!--#CHAPTER-->…{{CHAPTER_TITLE}} {{CHAPTER_TIME}}…
    <!--#ENTRY-->…{{SPEAKER}} {{COLOR}} {{AVATAR}} {{TS}} {{PARAS_HTML}} {{IDX}}…<!--/ENTRY-->
  …<!--/CHAPTER-->
  ```
- 纯文档型模板只需 `{{BODY}}`（整篇渲染注入）
- 交互 JS（筛选/搜索等）写在模板内，通过占位符注入数据，换模板即换功能

## 5. render.py CLI 契约

```bash
python scripts/render.py <输入.md> --template <set>/<doc> [--mindmap <png>] [--out <html>] [--title 覆盖标题]
# 例：
python scripts/render.py 会议实录（修正）.md --template research-report/minutes --out 访谈纪要.html
python scripts/render.py 会议总结.md --template clean-doc/summary --mindmap 思维导图.png --out 会议总结.html
```

- 自动识别输入类型：含 `**发言人** 时间` 块 → 按纪要型解析；否则按文档型（与所选模板 doc 类型不符时报错提示）
- 发言人配色：模板可带 `<!--COLORS: 名字=#hex,…-->` 预置映射，缺省用内置 16 色轮按出现顺序分配
- `doctor.py --check-template <文件>` 校验占位符拼写与块闭合

## 6. SKILL.md 工作流（9 环节映射）

| 环节 | 方式 | 兜底 |
| --- | --- | --- |
| ①爬取 | `fetch_minutes.py <url>`（playwright 持久 profile，默认 `<skill>/.auth/`；首次弹浏览器扫码登录） | 失败时按 reference/feishu-api.md 用 MCP 浏览器手动执行 |
| ②实录 | `build_transcript.py minutes_raw.json` | — |
| ③ASR | `asr.py <音频> [--model large-v3-turbo]`（HF_ENDPOINT=hf-mirror 降级；无音频跳过） | — |
| ④校正 | Agent 读双源逐段比对 → 写 corrections.json（old/new/expect/basis）→ `apply_corrections.py` 执行并校验段落数一致 | — |
| ⑤润色 | Agent 按 reference/pipeline.md 改写：合并同一发言人连续发言为时间块、书面化、段内 **1）2）** 逻辑分段、章节划分 | — |
| ⑥总结 | Agent 生成：会议信息头+按主题分节+关键数字加粗+引用块 | — |
| ⑦导图 | Agent 手写 .mmd（层级≤3、节点≤15字）→ `mmdc` 渲染 PNG | mmdc 失败→仅嵌源码块 |
| ⑧渲染 | `render.py` ×2（set 任选，纪要与总结建议同 set） | — |
| ⑨验证 | 可选：agent 浏览器打开截图抽查 | — |

**pipeline.md 沉淀本次验证过的原则**（举例）：妙记质量通常优于 whisper，校正只采信可交叉印证处；无把握保留原文；润色只顺句不改意；存疑处标"（录音模糊）"；关键数字清单须逐项 grep 核对。

**feishu-api.md 沉淀**：三端点（speakers / subtitles/paragraph-ids / subtitles_v2）的 URL、参数、字段路径、分页策略；MCP 浏览器手动爬取的完整步骤（网络面板发现→页面上下文 fetch→触发下载落盘，避免大 JSON 过上下文）。

## 7. 依赖与 doctor

- Python 包：playwright（含 `playwright install chromium`）、faster-whisper
- 系统工具：ffmpeg、Node+mmdc（mermaid-cli）
- `doctor.py` 逐项检查并给出安装命令；CPU 转录约 1.2 倍时长（66 分钟音频约 80 分钟），SKILL.md 提示可后台跑并与爬取/校正并行

## 8. 验收标准

1. 新会话只给 skill 文件夹 + 妙记 URL + 音频，能按 SKILL.md 跑通全流程产出两个 HTML
2. `render.py` 对 5 个 set 全部模板一键套壳成功；同 set 纪要与总结视觉一致
3. `doctor.py` 全绿；`--check-template` 能拦截占位符错误
4. 修正/润色环节产物为纯 markdown，随时可手工编辑后重渲染
5. skill 文件夹整体拷贝到其他机器（含依赖环境）即可使用，内部无绝对路径引用

## 9. 范围外（Out of Scope）

- 说话人分离（diarization）——发言人以妙记为准
- 腾讯会议/Zoom 等其他会议来源（架构留了扩展位：换 ①爬取脚本即可）
- Word/PPT 导出、发布到飞书文档
- 模板在线编辑器（模板就是 HTML 文件，手工改即所得）
