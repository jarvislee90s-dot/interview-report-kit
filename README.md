# interview-report-kit

飞书妙记访谈 → 可编辑 Markdown → 可换肤 HTML 报告的一站式工具集。

输入一个飞书妙记链接（+可选本地录音），产出带发言人归属的访谈实录、交叉校正与润色稿、会议总结、Mermaid 思维导图，最终用 5 套内置模板一键渲染成单文件 HTML（纪要版 + 总结版），零外部依赖、双击即开、可直接打印为 PDF。

```
妙记 URL ──① fetch_minutes.py──▶ minutes_raw.json ──② build_transcript.py──▶ 会议实录.md
本地音频 ──③ asr.py──────────▶ transcript.txt          （④ 校正 ⑤ 润色 ⑥ 总结 ⑦ 导图：LLM 按 pipeline.md 执行）
任选模板 ──⑧ render.py────────▶ 访谈纪要.html + 会议总结.html
```

## 快速开始

```bash
pip install -r requirements.txt
playwright install chromium          # 爬取用；另需系统安装 ffmpeg 与 Node+mmdc
python scripts/doctor.py             # 环境自检，全 ✅ 后继续

python scripts/fetch_minutes.py <妙记URL>          # 首次运行弹浏览器扫码登录，之后免登
python scripts/build_transcript.py minutes_raw.json
python scripts/asr.py <本地音频>                    # 可选；无音频则跳过校正环节
# ④⑤⑥⑦ 由 LLM 按 reference/pipeline.md 执行（产物均为可编辑 markdown）
python scripts/render.py 会议实录（修正）.md --template research-report/minutes --out 访谈纪要.html
python scripts/render.py 会议总结.md    --template research-report/summary --mindmap 思维导图.png --out 会议总结.html
```

任意 markdown 修改后重跑 `render.py` 即可重新出稿；`render.py` 也可脱离流水线单独给任何 md 套模板。

## 模板库（5 套 set × 纪要/总结双版式）

| set | 风格 | 适用 |
| --- | --- | --- |
| `research-report` | 藏青+鎏金研报风，衬线标题、搜索/进度条交互 | 正式外发、机构风 |
| `clean-doc` | 零 JS 纯文档、纸白灰调 | 打印最优、归档 |
| `modern-card` | 亮色渐变 Hero + 圆角卡片 | 内部分享、轻快 |
| `chat-bubble` | IM 左右气泡按发言人着色 | 轻松易读的对话感 |
| `timeline` | 垂直时间轴串联发言 | 快速浏览定位 |

模板是自包含 HTML（CSS/JS 内联），复制一套目录改样式即成新模板，`python scripts/doctor.py --check-template <文件>` 校验合法性。

## 目录结构

```
├── SKILL.md                  # Agent 工作流入口（9 环节）——也可作为人工操作手册
├── scripts/                  # 6 个独立 CLI：doctor / fetch_minutes / build_transcript / asr / apply_corrections / render
├── reference/
│   ├── templates/            # 5 套模板 set（minutes + summary）
│   ├── pipeline.md           # LLM 环节操作细则（校正/润色/总结/导图原则）
│   └── feishu-api.md         # 妙记接口手册 + 爬取失败手动兜底流程
├── tests/                    # pytest（16 项，含 doctor↔render 占位符契约锁定）+ 真实数据夹具
├── docs/                     # 设计文档与实施计划（本 skill 的演进档案）
└── examples/demo-interview/  # 演示示例：一次虚构路演访谈的全套产物（纪要/总结 HTML、md、思维导图）
```

## 环境要求

Python ≥3.10；ffmpeg；Node.js + `npm i -g @mermaid-js/mermaid-cli`；CPU 转录约为音频时长 1.2×。

## 数据与隐私

`tests/fixtures/` 与 `examples/` 使用**虚构演示数据**（化名发言人、虚构发行人 OceanDemo 与示例链接/token），可安全公开。用真实会议数据跑流水线时，产物仅落在本机工作目录；登录态（`.auth/`）已被 gitignore，永不入库。

## 许可

内部工具，未定开源许可（待补充）。
