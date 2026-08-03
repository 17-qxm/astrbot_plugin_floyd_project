# 更新日志

## v0.3.0

### 重构
- **目录结构重组**：图像渲染归集到 `imagecreate/`（card_renderer + summary_renderer + 字体）；WebUI 后端归集到 `webui/`（web_api.py）；前端 `pages/admin/` 受 AstrBot 硬编码约束保持不动
- **WebUI 全面重写**：vanilla JS → **Vue 3（CDN，无构建）**，Linear/GitHub 深色风设计系统（紫色 `#8b5cf6` 强调、6px 圆角、紧凑信息密度）
- **信息架构**：三个 tab 平铺（文案库 / 数据 / 设置），移除设置抽屉

### 文案库
- **精简为只读 + 导入**：移除行内编辑、删除、新增、AI 生成（后端 `challenges/generate` 端点同步移除）
- **新增「今日预览」**：按起算日算出 Day N，高亮显示当日推送文案
- **新增「排期预览」**：未来 7 天每天对应的 Day 号 + 文案，便于提前看轮播节奏
- 保留：导出 .txt、上传 .txt、文本框粘贴导入（追加/覆盖）、搜索、来源筛选、分页（每页 50）

### 数据视图
- **GitHub 式热力图**：7 行×N 列矩阵布局 + 月份标签 + 星期标签 + 悬停 tooltip（替代旧版平铺色块墙）
- **排行榜**：前三名奖牌 emoji + QQ 头像（前端拼 q.qlogo.cn）+ 排序维度切换
- **今日歌单**：每条带封面缩略图位（失败显示占位）
- **总览卡片**：累计 / 参与人数 / 今日 / 最长连续

### 设置（新 tab，原抽屉内容并入）
- **插件配置进 WebUI**：按 `_conf_schema.json` 自动渲染表单（目标群增删、时间 time input、发送日 select、模式 select、起算日 date input、总结图 switch）
- 后端新增 `GET/POST /config`，写入走 `AstrBotConfig.save_config_async`，持久化到 `data/config/`
- 保存后**不自动 reload**，提示「需在 Dashboard 重载插件后生效定时任务变更」

### 加载与状态体验
- **骨架屏**（shimmer 动画）替代「加载中…」纯文字
- **stale-while-revalidate 缓存**：切 tab 回来秒显缓存 + 后台静默刷新
- **Promise.allSettled 并发**：数据视图 4 个请求互不阻塞，失败区域单独「重试」
- **toast 队列**：多 toast 堆叠不覆盖
- 顶栏实时状态条（文案数 / 模式 / 今日打卡），30s 轮询

### 渲染修复（summary_renderer）
- **2x 高清渲染**：引入 `S=2` 缩放因子，画布/字号/坐标全部 ×2，输出 1520 宽（@2x retina）
- 修复曲目条圆角外被填成直角（`_draw_track` 多余的全矩形 paste）
- 统计卡标签间距调整（`+6` → `+12`）
- 移除标题 emoji（字体不含 emoji 字形）
- 周报「7天趋势」改横向条形图 + 按打卡占比 4 级渐变色
- 周报紧凑条时间标签移至右上角、推荐人下移

### 日志
- 全部日志等级统一为 `info`（debug/warning/error → info）
- 关键成功节点补 info 日志：收到分享、卡片渲染完成、打卡成功、推歌/总结发送、配置保存等

### 开发支持
- `pages/admin/dev-mock.js`：本地预览假 bridge（`?dev=1` 加载，生产零影响）
- `pages/admin/components/`：9 个 Vue 组件（ChallengesView/DataView/SettingsView/Heatmap/RankTable/TodayList/Toast/Modal/Skeleton）
- `imagecreate/INTERFACE.md`：渲染层接口契约文档（函数签名、assets key 约定、调色板、待统一 TODO）

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
