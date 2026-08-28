# feishu-api.md —— 飞书妙记 web 接口手册 + 手动兜底

`fetch_minutes.py` 内嵌的抓取逻辑即调这些接口（页面上下文同源 fetch）。接口字段路径为 **2026-03-10 实测**。当脚本响亮失败（页面上下文抓取异常 / 零段落 / 段数不足 90%）时，按第 3 节手动兜底。

## 1. 端点清单（均 GET，需带妙记页面 cookie）

设 `{T}` 为妙记 token（见第 2 节），host 为妙记页所在域名（如 `https://xxx.feishu.cn`）。

| 用途 | URL | 关键字段 |
|---|---|---|
| 发言人映射 | `/minutes/api/speakers?size=10000&translate_lang=default&object_token={T}&language=zh_cn` | `data.speaker_info_map`：`{uid: {"user_name": 姓名}}`；`data.paragraph_to_speaker`：`{pid: uid}` |
| 段落 id 清单 | `/minutes/api/subtitles/paragraph-ids?page_size=10000&page_num=0&object_token={T}&language=zh_cn` | `data.list`：`[{pid, start_time, stop_time}, ...]`（start/stop 为毫秒） |
| 段落正文（分页） | `/minutes/api/subtitles_v2?paragraph_id={cursorPid}&size=150&translate_lang=default&is_fluent=false&filter_speaker=true&object_token={T}&language=zh_cn` | `data.paragraphs`：`[{pid, start_time, sentences: [{contents: [{content: 文本片段}]}]}, ...]` |
| 会议信息（辅助） | `/minutes/api/clip?object_token={T}&language=zh_cn` | `data.start_time`（毫秒，`meeting_time` 来源；缺省回退 `create_time` 等） |

分页规则：`subtitles_v2` 每页最多 **150 段**；首页 cursor 取 `paragraph-ids` 清单的第一个 pid，此后每页取清单中**首个尚未抓到的 pid** 作 cursor，直到全部 pid 取齐；最终段落按 `start_time` 排序。段落文本 = 该段所有 `sentences[].contents[].content` 拼接。

## 2. token 提取

妙记 URL 形如 `https://xxx.feishu.cn/minutes/<token>`，token 为字母数字串，取路径 `/minutes/` 之后的一段即为 `{T}`。

## 3. 手动兜底步骤（fetch_minutes 失败时，agent 用 MCP 浏览器）

1. **打开妙记页**：浏览器 navigate 到妙记 URL，确认已登录（能看到转写文本；若被重定向到 `/accounts` 登录页，先完成登录）。
2. **找 XHR**：打开网络面板，过滤 `minutes/api`，刷新页面，确认上述接口真实存在、路径无变化。
3. **页面上下文取数**：在 evaluate 里同源调用（关键：`credentials: 'include'` 带上 cookie）：
   ```js
   const get = async (u) => (await fetch(u, { credentials: 'include' })).json();
   ```
   依次请求 speakers → paragraph-ids → 循环 subtitles_v2（每页 150，cursor = 清单中首个未取段落 pid）→ 拼段落：`{s: speaker_info_map[paragraph_to_speaker[pid]].user_name, t: Number(start_time), x: contents 拼接}` → 按 `t` 排序；再请求 clip 取 `data.start_time` 毫秒数转成 `meeting_time`。
   最省事的做法：**把 `scripts/fetch_minutes.py` 里的 `FETCH_JS` 常量（整个 async 箭头函数）直接复制进 evaluate 调用**，传 `{token, pageUrl}`，它按上面全部逻辑返回成品结构 `{url, title, meeting_time, total_expected, paras}`。
4. **大 JSON 不要过模型上下文**（1 小时会议的 paras 约 50KB+，读回来再写盘必然劣化/截断）：在**页面里**直接落盘——`new Blob` + `URL.createObjectURL` 触发浏览器下载：
   ```js
   const data = await FETCH_JS({token: "…", pageUrl: "…"});   // 页面上下文执行
   const a = document.createElement('a');
   a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], {type: 'application/json'}));
   a.download = 'minutes_raw.json';
   a.click();
   ```
   把下载的文件挪到项目目录即 `minutes_raw.json`，从工作流 ② 继续。
5. 自检：`paras` 段数 ≥ `total_expected` 的 90%，且每段 `s/t/x` 齐全（`s` 允许空串=未识别发言人）。

## 4. 登录态丢失

`.auth` 目录（默认 `<skill>/.auth`）损坏、过期或换机器时：删除该目录，重跑 `python <skill>/scripts/fetch_minutes.py "<妙记URL>"`，会重新弹浏览器扫码；登录态再次持久化。

## 5. 接口变更迹象

出现以下任一情况，说明飞书改了接口，**此时才需要人工抓包比对字段名**（网络面板里逐个核对本手册第 1 节的字段路径，更新 `fetch_minutes.py` 的 `FETCH_JS`）：

- 响应里关键字段缺失（`data.list` / `data.paragraphs` / `data.speaker_info_map` 为空或不存在）；
- 抓到的段数 < `total_expected` 的 90%（脚本会以 `❌ 抓取不完整：N/M 段` 退出）；
- 页面报错/接口 4xx 5xx。
