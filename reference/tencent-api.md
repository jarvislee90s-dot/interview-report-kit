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

另注意：腾讯会**服务端重新分段**（段落 `pid` 与时间线重排，两次抓取的段数/首段可能不同），属正常现象，不是抓取缺陷。

出现以下情况说明腾讯改了接口，此时才需要重新核对 §1/§2 字段：`minutes/detail` 返回 code≠0 或无 `minutes` 键；`paragraphs[].speaker / start_time / sentences` 字段名变化；分页 `pid` 游标不推进（同页重复返回，guard 2000 页内未收敛）。

## 5. 登录态

`.auth`（与 fetch_feishu 共用）仅在有访问密码/要求登录的分享页有用；公开链接不需要。换机器或损坏时删除 `.auth` 重跑。