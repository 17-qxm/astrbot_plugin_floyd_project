# webui — WebUI 后端 API

本目录归集 WebUI 的**后端**代码。当前仅 `web_api.py`（Quart 路由），
通过 `context.register_web_api` 注册，路由前缀为插件名 `/{PLUGIN_NAME}/...`。

## 为何前端 `pages/` 没有一起迁进来？

AstrBot 的 Plugin Page 发现逻辑**硬编码**要求前端静态资源放在插件根目录的 `pages/` 下：

- 源码：`astrbot/dashboard/services/plugin_page_service.py`
  - `PLUGIN_PAGE_ROOT_DIR_NAME = "pages"`（第 25 行，常量，无配置覆盖）
  - `PLUGIN_PAGE_ENTRY_FILE_NAME = "index.html"`（第 26 行）
- `discover_plugin_pages()` 只扫描 `pages/<page_name>/index.html`，
  目录名不是 `pages` 时返回空，Dashboard 里该插件页直接消失。

因此前端静态资源（`pages/admin/index.html` 等）必须留在插件根目录的 `pages/admin/`，
无法随本目录一起挪进 `webui/`。这是 AstrBot 的约束，不是本插件的设计选择。

## 当前分工

| 位置 | 内容 |
|------|------|
| `webui/web_api.py`（本目录） | 后端 API handler（Quart） |
| `pages/admin/`（插件根，不可迁移） | 前端 HTML/JS/CSS，AstrBot 自动挂载 |
