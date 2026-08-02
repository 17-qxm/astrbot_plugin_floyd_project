# 更新日志

## v0.2.0

### 新增
- **每周总结**：`templates/weekly_summary.html` 模板 + `run_weekly_task` 定时任务，在指定星期（默认周日）22:30 自动发本周汇总
- **`/weekly` 指令**：手动查看本周打卡总结（图片/文本）
- **周报管理面板**：7 天柱状趋势图、按天分组、紧凑歌曲条（含封面模糊背景）
- **封面模糊背景**：每日/每周总结的每首歌卡片，背景用该歌封面放大模糊铺底
- **推荐人头像**：每首歌卡片显示 `由 [头像] [QQ名] 推荐`，头像通过 QQ 号实时拉取，靠右对齐
- **毛玻璃时间标签**：时间戳改为 `backdrop-filter: blur` 透出封面色调
- **CHANGELOG.md**：供 WebUI/OpenAPI changelog 端点读取

### 变更
- **配置合并**：`push_target_group` + `checkin_groups` 合并为单个 `target_groups`（list 类型，Dashboard 可视化增删），既是打卡群也是推送目标
- **多群推送**：三个定时任务（推歌/每日/周报）改为遍历所有目标群推送，发图失败的群自动补发文本
- **`/summary` 指令**：改为优先发图片（`auto_summary_image` 开启时），与 `/weekly` 行为一致
- **`/forcepush` 指令**：改为主动推送到目标群（原为仅回复调用者）
- **打卡记录**：新增 `cover_url`/`song_id`/`album`/`uid` 字段，供总结模板渲染封面和头像

### 修复
- 修复 WebUI 排行榜加载失败：bridge endpoint 禁止含 query string，`by`/`limit` 改走 params
- 修复文案编辑失败：POST `/challenges` 带 `idx` 时正确走更新逻辑（原忽略 idx 当新增）
- 修复 AI 生成 internal server error：`llm_generate` 调用增加详细异常捕获与 traceback，响应文本取值多字段兜底
- 修复总结卡片渲染失败时日志信息不全：补充完整堆栈输出

## v0.1.0

### 初始重构版本
- 从旧 `floydproject` 重构为乐队群专用插件
- **网易云分享卡片**：aiohttp 异步取歌/封面/头像，Pillow 绘制深色磨砂卡片
- **每日推歌挑战**：定时推送，文案支持手动录入/批量导入/AI 生成，`sequential`/`daily_ai` 两种模式
- **打卡统计**：分享即打卡（每人每天 1 次），KV 持久化，连续天数/总打卡/排行榜
- **每日总结**：固定时间发当日汇总（图片/文本）
- **WebUI 管理面板**：文案 CRUD + AI 生成 + 导入导出 + 打卡热力图 + 排行榜（Dashboard 插件页）
- 全程异步（aiohttp + `asyncio.to_thread`），UMO 跨平台自动捕获
- 砍除旧版喜报/悲报/吃什么/helloworld/debug 等无关功能
