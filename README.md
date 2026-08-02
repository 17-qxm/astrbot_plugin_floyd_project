# Floyd 乐队群

AstrBot 插件 —— 面向乐队群的三件套：**网易云分享卡片** + **每日推歌挑战** + **打卡统计与每日总结**，并附带一个 WebUI 管理面板。

## 功能

### 🎵 网易云分享卡片
群里发送网易云音乐分享，自动生成深色磨砂风格的卡片（含封面 / 歌名 / 歌手 / 专辑 / 推荐人头像）。
- 走网易云 web 端接口取完整歌曲信息（无需 API Key）
- 推荐人头像通过 QQ 号自动获取，失败时用首字母占位
- 全程异步（aiohttp），不会阻塞 bot

### 📅 每日推歌挑战
按设定时间向目标群推送当日主题。文案三种来源：
- **手动录入**（WebUI 添加）
- **上传 .txt 批量导入**
- **AI 一键生成**（调用 AstrBot 的 LLM）

两种模式：
- `sequential`：按文案库顺序逐日轮播，列表耗尽后循环
- `daily_ai`：每天用 AI 现生成一条

### 📊 打卡统计与每日总结
- **打卡规则**：在打卡群发网易云分享并**成功生成卡片**即记为当天一次（每人每天最多 1 次）。
- **每日总结**：固定时间（默认 22:00）自动发送当日打卡汇总（图片或纯文本）。
- **统计**：总打卡数 / 当前连续天数 / 最长连续 / 排行榜，KV 持久化，重启不丢。

### 🎛 WebUI 管理面板
AstrBot Dashboard 里的「Floyd」页面，提供：
- 文案库增删改查 + 导入导出 + AI 批量生成
- 打卡统计总览、90 天热力图、排行榜
- 数据自愈（重算统计）

## 安装

1. 将本目录放入 AstrBot 的 `data/plugins/` 下
2. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

3. 重启 AstrBot，在管理面板启用本插件

## 配置（`_conf_schema.json` / Dashboard）

| 字段 | 说明 | 默认 |
|------|------|------|
| `target_groups` | 目标群号列表（既是打卡群，也是推送目标） | `[]` |
| `push_time` | 每日推歌时间 | `08:00` |
| `summary_time` | 每日总结时间 | `22:00` |
| `weekly_time` | 每周总结时间 | `22:30` |
| `weekly_day` | 每周总结发送日（1=周一 … 7=周日） | `7`（周日） |
| `challenge_mode` | 文案来源模式 | `sequential` |
| `challenge_start_date` | Day1 起算日 | `2026-04-13` |
| `gen_provider` | AI 生成用的 LLM Provider | （空，回落当前会话） |
| `auto_summary_image` | 总结是否渲染成图片 | `true` |

> ⚠️ **首次使用**：定时推送/总结需要插件先「见过」目标群的消息以捕获 unified_msg_origin。请在目标群发任意一条消息，让插件记录 UMO。

## 指令

| 触发 | 权限 | 说明 |
|------|------|------|
| 打卡群发网易云分享 | 全员 | 生成卡片 + 记一次打卡 |
| `/forcepush` | 管理员 | 手动发当日推歌主题 |
| `/summary` | 全员 | 查看当日打卡总结 |
| `/weekly` | 全员 | 查看本周打卡总结（近 7 天） |
| `/streak` | 全员 | 查我的连续/总打卡 |
| `/rank` | 全员 | 打卡排行榜（总打卡数） |

## 结构

```
astrbot_plugin_floyd_project/
├── main.py                 # 插件入口（Star 类）
├── netease.py              # 异步：歌曲 ID 提取 + 网易云接口 + 封面/头像下载
├── card_renderer.py        # Pillow 卡片渲染
├── card_service.py         # 卡片生成编排（异步）
├── challenge.py            # 文案库管理（CRUD / 导入导出）
├── checkin.py              # 打卡记录 / 统计 / 排行（KV）
├── ai_generator.py         # AI 文案生成（批量 / 每日）
├── scheduler.py            # 定时任务 + UMO 跨平台适配
├── web_api.py              # WebUI 后端路由（Quart）
├── templates/
│   └── daily_summary.html  # 每日总结卡片模板（Jinja2 → PNG）
├── pages/
│   └── admin/              # WebUI 管理面板（HTML/JS/CSS）
├── _conf_schema.json
├── metadata.yaml
├── requirements.txt
├── Harmonyossans.ttf       # 卡片字体
├── song_push.txt           # 初始默认文案（首次启动自动导入）
├── LICENSE
└── .gitignore
```

## 依赖

- AstrBot `>=4.16`（WebUI Plugin Pages 需较新版本）
- Python 3.12+
- `aiohttp`、`Pillow`

## 技术说明

- **全异步**：网络请求走 `aiohttp`，PIL 渲染用 `asyncio.to_thread` 放入线程池，绝不阻塞事件循环。
- **跨平台**：定时推送的 unified_msg_origin 从群消息事件自动捕获并缓存，不写死 `Floyd:GroupMessage:` 前缀。
- **数据隔离**：打卡记录走 AstrBot KV 存储（`data/metadata/kv_storage.db`），文案库走 `plugin_data/<name>/challenges.json`。

## License

AGPL-3.0
