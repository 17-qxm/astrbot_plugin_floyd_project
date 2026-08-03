# imagecreate — PIL 图像渲染接口契约

本目录是插件所有 PIL 图像渲染的归集点。**同步、CPU/IO 密集**，调用方（异步层）
必须用 `asyncio.to_thread(render_fn, ...)` 包裹，禁止在事件循环里直接调用。

## 模块一览

| 模块 | 状态 | 职责 |
|------|------|------|
| `card_renderer.py` | **已定型，请勿改动** | 单首歌分享卡片（深色磨砂 + 封面模糊背景 + 推荐人头像条） |
| `summary_renderer.py` | 当前实现，待后续规范化 | 每日 / 每周打卡总结卡（与歌曲卡同风格） |

字体文件 `Harmonyossans.ttf` 必须与本目录下的 renderer 同级——
`card_renderer._find_font` 和 `summary_renderer.FONT_PATH` 都通过
`SCRIPT_DIR = Path(__file__).parent` 探测字体，挪走会回退系统字体导致风格变化。

---

## card_renderer.py（已定型）

### `render_card(...)`

```python
def render_card(
    song: dict,            # 含 name / artists / album（来自 netease.fetch_song_detail）
    cover_bytes: bytes,    # 封面原始字节（来自 netease.download_cover）
    output_path: str,      # PNG 输出路径
    font_path: Optional[str] = None,        # 传 None 让 _find_font 自行探测
    recommender: Optional[str] = None,      # 推荐人昵称，底部头像条文字
    avatar_bytes: Optional[bytes] = None,   # 推荐人头像字节，无则画首字母占位圆
) -> str                   # 返回 output_path
```

- 画布 `880×380`，圆角 `24`，底部推荐人条高 `66`。
- 背景 = 封面放大 + `GaussianBlur(42)` + 半透明黑遮罩 `alpha=158`。
- 标题最多 2 行，按像素宽度换行，溢出行 `…` 截断（见 `_wrap_text`）。

### 共享工具（summary_renderer 也依赖）

| 符号 | 签名 | 说明 |
|------|------|------|
| `FontLoader` | `FontLoader(font_path=None)`；`.get(size: int) -> FreeTypeFont` | 按字号缓存字体，避免重复 truetype 解析 |
| `_find_font` | `(font_path: Optional[str]) -> Optional[str]` | 字体探测链：显式参数 > 本目录 glob(`*.ttf/*.otf/*.ttc`) > 系统兜底列表 |
| `_round_corners` | `(im: Image, radius: int) -> Image` | 给图片加圆角透明遮罩 |
| `_make_avatar` | `(bytes, diameter, font, initial) -> Image` | 圆形头像，无字节画首字母占位圆 |
| `WHITE` | `(255, 255, 255)` | 常量 |

`_FONT_FALLBACKS`（系统兜底字体路径，仅当本目录无字体时生效）：
`C:/Windows/Fonts/HarmonyOS_Sans_SC.ttf` → `msyh.ttc` → `simhei.ttf`
→ `/System/Library/Fonts/PingFang.ttc` → `NotoSansCJK-Regular.ttc`。

---

## summary_renderer.py

### 调色板（与 card_renderer / 旧 HTML 模板一致）

| 常量 | RGB | 用途 |
|------|-----|------|
| `BG` | `(15, 18, 38)` | 整体背景 `#0f1226` |
| `PANEL` | `(26, 31, 61)` | 卡片底 `#1a1f3d` |
| `PANEL_BORDER` | `(42, 49, 88)` | `#2a3158` |
| `TEXT` | `(231, 233, 243)` | 主文本 |
| `TEXT_DIM` | `(154, 160, 192)` | 次级文本 |
| `TEXT_FAINT` | `(107, 113, 150)` | 弱化文本 |
| `ACCENT` / `ACCENT_BAR` | `(124, 156, 255)` | 强调色 `#7c9cff` |
| `WHITE_DIM` | `(216, 216, 216)` | 歌名/歌手次级白 |

### `render_daily(...)`

```python
def render_daily(
    checkins: list[dict],   # 已按时间升序；每项含 name/song/artist/time/uid
    *,
    date_str: str,          # 如 "2026-08-03"
    total_users: int,       # 累计参与人数（stats）
    output_path: str,       # PNG 输出路径
    assets: Optional[dict] = None,
) -> str
```

**`assets` key 约定**：
- 封面：`"cover_{i}"` → `{"cover": bytes|None}`，`i` 是 checkin 在列表里的索引。
- 头像：`"{uid}"` → `{"avatar": bytes|None}`，`uid` 去重全局复用。

### `render_weekly(...)`

```python
def render_weekly(
    days: list[dict],       # get_week() 返回的 days；每项 {date, weekday, count, checkins}
    *,
    start: str, end: str,
    total_checkins: int, participants: int,
    output_path: str,
    assets: Optional[dict] = None,
) -> str
```

**`assets` key 约定**（双索引，与 daily 不同）：
- 封面：`"d{di}_cover_{ci}"` → `{"cover": bytes|None}`，`di` 天索引、`ci` 当天曲目索引。
- 头像：`"{uid}"` → `{"avatar": bytes|None}`。

### 内部工具（私有，不对外承诺稳定）

`_blur_cover_bg`（封面放大模糊 + 暗化遮罩做窄条背景）、`_circle_avatar`（圆形头像 / 首字母占位）、
`_truncate`（按像素截断加省略号）、`_draw_stat_card`（统计小卡）、
`_draw_track` / `_draw_track_compact`（每日宽条 / 周报紧凑条）。

---

## 调用约定（重要）

1. **调用方负责异步下载资源**：`assets` 里的 bytes 必须由调用方（`scheduler._download_assets`）
   用 `aiohttp` 并发下载好后传入，renderer 内部不做网络请求。
2. **调用方负责 `asyncio.to_thread`**：renderer 全是同步 PIL 调用，直接在协程里调会阻塞事件循环。
3. **失败兜底**：assets 缺失 / bytes 解析失败时，renderer 用纯色面板 + 首字母占位降级，**不抛异常**。
4. **输出目录**：调用方保证 `output_path` 的父目录存在（`scheduler` 用 `CARD_CACHE_DIR`）。

---

## 待统一约定（TODO，留给后续调整）

- [ ] `assets` 的 key 命名在 daily/weekly 不一致（`cover_{i}` vs `d{di}_cover_{ci}`），
      后续可统一为 `("cover", day_idx, item_idx)` 元组 key 或抽出 `AssetBundle` 数据类。
- [ ] 字体路径探测逻辑散落在 `card_renderer._find_font` 和 `summary_renderer.FONT_PATH` 两处，
      后续可收敛到单一入口。
- [ ] 调色板常量目前定义在 `summary_renderer`，`card_renderer` 用的是硬编码 RGB 元组，
      后续可抽公共 `palette.py`。
- [ ] 错误兜底策略（`except Exception: pass`）散落各函数，后续可统一为装饰器或显式 `try/except` 层。
