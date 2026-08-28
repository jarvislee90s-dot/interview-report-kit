# Changelog

显著变更记录（语义化版本）。各版本的设计与实施细节见 `docs/` 下对应 spec 与 plan。

## [1.2.0] - 2026-08-28

### 新增
- **③′ 录音分离转录**：`asr_diarize.py`（FunASR paraformer-zh + cam++ 说话人分离）→ 带匿名标签 `spk:N` 的 `minutes_raw.json`，结束时打印每号声音首/中/末样例句；断点续跑。实测 CPU RTF ≈ 0.3（1 小时音频约 20 分钟）。
- **对话式标记发言人**：`build_transcript.py --rename "spk:0=名字,..."` 一步落名（SKILL.md ③′ 工作流 + pipeline.md §7 标记纪律）。
- 重依赖可选安装：`requirements-diarize.txt`（funasr / modelscope / torch / torchaudio——torchaudio 为 funasr 1.4.x 必需的 fbank 后端）；`doctor.py` 增加 funasr 可选检查（缺失仅 ⚠️）。

### 修复（含 code review 收尾）
- `asr_diarize.py` 兼容 funasr 1.4.x 句级键名 `sentence_info`（实测冒烟发现，旧键名 `sentence` 为空）。
- `apply_corrections.py` 段落数守卫适配无时间戳契约（此前"无时间戳来源 + 录音"走 ④ 校正时守卫静默失效）。
- `fetch_tencent.py` evaluate 失败转响亮退出并指引 `tencent-api.md` 手动兜底。
- 文档过期项清理（SKILL.md 检查项/产物结构、README 徽章与环节计数）；`.gitignore` 增加 `asr_runs/`。

## [1.1.0] - 2026-08-28

### 新增
- **①′ 腾讯会议录制分享抓取**：`fetch_tencent.py`（公开链接免登录、页面上下文分页取逐字稿、可选抓腾讯 AI 纪要作参考、无发言人检测；接口手册 `reference/tencent-api.md` 含手动兜底流程）。
- **①″ 本地纪要文档通道**：`extract_text.py`（md/txt/docx/pdf → 纯文本，零启发式结构识别）+ agent 结构化环节；其他转写网页经浏览器复制同通道。
- **`minutes_raw.json` 契约微扩（向后兼容）**：`t` 可缺省（无时间戳来源）、新增 `source_label` 来源名。
- `build_transcript.py`：`source_label` 来源行、无 `t` 段落输出无时间戳行、`--rename`、全员无发言人告警。
- `render.py` 纪要版式 `ENTRY_RE` 时间戳可选（无时间戳来源在 4/5 套模板下安全降级，timeline 不建议）。
- `speaker_check.py` 公共无发言人检测（场景 5：无发言人来源自动降级快速总结线）。
- SKILL.md 第 ⓪ 环节输入路由（8 场景矩阵）+ 仅录音快速总结线（单产物）；doctor 增加 docx/pypdf 检查；README 多源化与发布同步清单。
- 测试 18 → 40 项（新增 fetch_tencent 解析、extract_text 格式、build_transcript 扩展、render 无时间戳等）。

### 变更
- `fetch_minutes.py` 更名 **`fetch_feishu.py`**（多源化命名清理；`minutes_raw.json` 作为来源无关契约保留原名）。

## [1.0.0] - 2026-08-27

- 首个公开版：飞书妙记访谈实录 → 纪要/总结 HTML 工具集（9 环节流水线：爬取 → 实录 → ASR → 交叉校正 → 润色 → 总结 → 思维导图 → 渲染；5 套模板 × 2 版式；md 唯一事实源）。
