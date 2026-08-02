// Floyd 管理面板逻辑 — 纯 vanilla JS，依赖 AstrBot 注入的 window.AstrBotPluginPage bridge。
// 三个 hash 路由：#challenges / #stats / #tools

const bridge = window.AstrBotPluginPage;

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

let toastTimer = null;
function toast(msg, isErr = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast"; }, 2600);
}

// bridge apiGet/apiPost 在 reject 时返回的 err 形态不一，统一处理。
// 注意：bridge endpoint 不能含 query string，GET 的查询参数走 params。
async function api(method, endpoint, body) {
  try {
    if (method === "GET") return await bridge.apiGet(endpoint, body);
    if (method === "DELETE") return await bridge.apiPost(endpoint, body || {});
    return await bridge.apiPost(endpoint, body || {});
  } catch (e) {
    const msg = (e && (e.message || e.statusText)) || String(e);
    throw new Error(msg);
  }
}

async function safe(promise, errMsg) {
  try {
    const r = await promise;
    if (r && r.ok === false) throw new Error(r.error || errMsg || "请求失败");
    return r && r.data !== undefined ? r.data : r;
  } catch (e) {
    toast((errMsg || "操作失败") + "：" + e.message, true);
    throw e;
  }
}

// ---------- 路由 ----------
const ROUTES = ["challenges", "stats", "tools"];
function routeTo(name) {
  if (!ROUTES.includes(name)) name = "challenges";
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.route === name);
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("view-" + name).classList.remove("hidden");
  if (name === "challenges") loadChallenges();
  if (name === "stats") loadStats();
  if (name === "tools") loadState();
}

function initRouter() {
  document.querySelectorAll(".tab").forEach((b) => {
    b.addEventListener("click", () => {
      location.hash = b.dataset.route;
    });
  });
  const apply = () => {
    const h = (location.hash || "#challenges").slice(1);
    routeTo(h);
  };
  window.addEventListener("hashchange", apply);
  apply();
}

// ---------- 挑战文案 ----------
async function loadChallenges() {
  const data = await safe(api("GET", "challenges"), "加载文案失败");
  $("ch-count").textContent = data.length;
  const list = $("ch-list");
  list.innerHTML = "";
  if (!data.length) {
    list.appendChild(el("li", "empty-state", "文案库为空，点上方「添加」或「AI 生成」开始。"));
    return;
  }
  data.forEach((item) => list.appendChild(renderChItem(item)));
}

function renderChItem(item) {
  const li = el("li", "ch-item");
  li.appendChild(el("span", "num", "#" + item.idx));
  const txt = el("span", "text", item.text);
  li.appendChild(txt);
  li.appendChild(el("span", "src", item.source || "manual"));

  const acts = el("div", "actions");
  const editBtn = el("button", null, "✎");
  editBtn.title = "编辑";
  editBtn.addEventListener("click", () => startEdit(li, txt, item));
  const delBtn = el("button", "danger", "✕");
  delBtn.title = "删除";
  delBtn.addEventListener("click", () => delChallenge(item.idx));
  acts.appendChild(editBtn);
  acts.appendChild(delBtn);
  li.appendChild(acts);
  return li;
}

function startEdit(li, txtSpan, item) {
  const input = el("input", "ch-edit");
  input.type = "text";
  input.value = item.text;
  li.replaceChild(input, txtSpan);
  input.focus();
  input.select();
  const commit = async () => {
    const v = input.value.trim();
    if (!v) { toast("内容不能为空", true); return; }
    await safe(api("POST", "challenges", { idx: item.idx, text: v }), "更新失败");
    toast("已更新");
    loadChallenges();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") commit();
    if (e.key === "Escape") loadChallenges();
  });
  input.addEventListener("blur", commit, { once: true });
}

async function addChallenge() {
  const input = $("ch-input");
  const text = input.value.trim();
  if (!text) { toast("请输入文案", true); return; }
  await safe(api("POST", "challenges", { text }), "添加失败");
  input.value = "";
  toast("已添加");
  loadChallenges();
}

async function delChallenge(idx) {
  if (!confirm("删除这条文案？")) return;
  await safe(api("DELETE", "challenges/delete", { idx }), "删除失败");
  toast("已删除");
  loadChallenges();
}

async function importBulk() {
  const raw = $("ch-bulk").value;
  if (!raw.trim()) { toast("文本框为空", true); return; }
  const mode = document.querySelector('input[name="import-mode"]:checked').value;
  const data = await safe(api("POST", "challenges/import", { raw, mode }), "导入失败");
  toast(`已${mode === "replace" ? "覆盖" : "追加"} ${data.affected} 条，共 ${data.total} 条`);
  $("ch-bulk").value = "";
  loadChallenges();
}

async function uploadTxt() {
  const f = $("ch-file").files[0];
  if (!f) { toast("请先选择 .txt 文件", true); return; }
  const mode = document.querySelector('input[name="import-mode"]:checked').value;
  try {
    const text = await f.text();
    const data = await safe(api("POST", "challenges/import", { raw: text, mode }), "上传导入失败");
    toast(`已${mode === "replace" ? "覆盖" : "追加"} ${data.affected} 条`);
    loadChallenges();
  } catch (e) {
    toast("读取文件失败：" + e.message, true);
  }
  $("ch-file").value = "";
}

async function exportTxt() {
  // bridge.download 走 GET；这里直接用 apiGet 拿不到 blob，改用 download。
  try {
    await bridge.download("challenges/export", {}, "challenges.txt");
  } catch (e) {
    toast("导出失败：" + (e.message || e), true);
  }
}

async function generate() {
  const count = parseInt($("gen-count").value, 10) || 10;
  const prompt = $("gen-prompt").value.trim() || undefined;
  const btn = $("gen-btn");
  btn.disabled = true;
  btn.textContent = "生成中…";
  $("gen-result").style.display = "none";
  try {
    const data = await safe(api("POST", "challenges/generate", { count, prompt }), "生成失败");
    $("gen-result").style.display = "block";
    $("gen-result").textContent = `成功入库 ${data.added} 条（provider: ${data.provider}）\n\n--- 原始输出 ---\n${data.raw}`;
    toast(`已生成并入库 ${data.added} 条`);
    loadChallenges();
  } finally {
    btn.disabled = false;
    btn.textContent = "开始生成";
  }
}

// ---------- 统计 ----------
async function loadStats() {
  loadOverview();
  loadHeatmap();
  loadRank();
  loadTodayList();
}

async function loadOverview() {
  try {
    const [stats, today] = await Promise.all([
      safe(api("GET", "checkin/stats"), "加载统计失败"),
      safe(api("GET", "checkin/today"), "加载今日失败"),
    ]);
    const users = stats.users || {};
    const todayCheckins = today.checkins || {};
    const vals = Object.values(users);
    const total = vals.reduce((s, u) => s + (u.total || 0), 0);
    const maxStreak = vals.reduce((s, u) => Math.max(s, u.max_streak || 0), 0);
    $("s-total").textContent = total;
    $("s-users").textContent = Object.keys(users).length;
    $("s-today").textContent = Object.keys(todayCheckins).length;
    $("s-streak").textContent = maxStreak;
  } catch (e) { /* safe 已 toast */ }
}

async function loadHeatmap() {
  const box = $("heatmap");
  box.innerHTML = "";
  try {
    const data = await safe(api("GET", "checkin/history"), "加载热力图失败");
    const days = data.days || {};
    const counts = Object.values(days).map((arr) => (arr || []).length);
    const max = Math.max(1, ...counts);
    Object.entries(days).forEach(([dateStr, arr]) => {
      const n = (arr || []).length;
      const level = n === 0 ? 0 : Math.min(4, Math.ceil((n / max) * 4));
      const cell = el("div", "heat-cell" + (level ? " l" + level : ""));
      cell.title = `${dateStr}：${n} 人`;
      box.appendChild(cell);
    });
  } catch (e) { /* safe 已 toast */ }
}

async function loadRank() {
  const by = $("rank-by").value;
  const body = $("rank-body");
  body.innerHTML = '<tr><td colspan="4" class="loading">加载中…</td></tr>';
  try {
    const data = await safe(api("GET", "checkin/rank", { by, limit: 20 }), "加载排行失败");
    const rank = data.rank || [];
    if (!rank.length) {
      body.innerHTML = '<tr><td colspan="4" class="empty-state">还没有打卡记录</td></tr>';
      return;
    }
    body.innerHTML = "";
    rank.forEach((u, i) => {
      const tr = el("tr");
      tr.appendChild(el("td", "pos" + (i < 3 ? " top" : ""), String(i + 1)));
      tr.appendChild(el("td", null, u.name || u.user_id));
      tr.appendChild(el("td", "num", String(u[by] ?? 0)));
      tr.appendChild(el("td", "muted", u.last_date || "-"));
      body.appendChild(tr);
    });
  } catch (e) { /* safe 已 toast */ }
}

async function loadTodayList() {
  const ul = $("today-list");
  ul.innerHTML = '<li class="loading">加载中…</li>';
  try {
    const today = await safe(api("GET", "checkin/today"), "加载今日失败");
    const checkins = today.checkins || {};
    ul.innerHTML = "";
    const entries = Object.entries(checkins);
    if (!entries.length) {
      ul.appendChild(el("li", "empty-state", "今天还没有人打卡 🎵"));
      return;
    }
    entries.forEach(([uid, info], i) => {
      const li = el("li", "ch-item");
      li.appendChild(el("span", "num", String(i + 1)));
      const wrap = el("div");
      wrap.style.flex = "1";
      wrap.appendChild(el("div", "song-name", info.song || "?"));
      wrap.appendChild(el("div", "artist", info.artist || ""));
      li.appendChild(wrap);
      li.appendChild(el("span", "recommender", "推荐 · " + (info.name || uid)));
      ul.appendChild(li);
    });
  } catch (e) { /* safe 已 toast */ }
}

// ---------- 工具 ----------
async function loadState() {
  const box = $("state-box");
  const pill = $("state-pill");
  try {
    const data = await safe(api("GET", "state"), "加载状态失败");
    box.textContent = JSON.stringify(data, null, 2);
    pill.innerHTML = `文案 <b>${data.challenge_count}</b> · 模式 <b>${data.challenge_mode}</b>`;
  } catch (e) { /* safe 已 toast */ }
}

async function rebuild() {
  if (!confirm("根据全部历史记录重算统计？这会覆盖现有 stats。")) return;
  const data = await safe(api("POST", "checkin/rebuild"), "重算失败");
  toast(`已重算，覆盖 ${data.users} 位用户`);
}

// ---------- 启动 ----------
async function main() {
  await bridge.ready();

  $("ch-add-btn").addEventListener("click", addChallenge);
  $("ch-input").addEventListener("keydown", (e) => { if (e.key === "Enter") addChallenge(); });
  $("ch-import-btn").addEventListener("click", importBulk);
  $("ch-upload-btn").addEventListener("click", () => $("ch-file").click());
  $("ch-file").addEventListener("change", uploadTxt);
  $("ch-export-btn").addEventListener("click", exportTxt);
  $("gen-btn").addEventListener("click", generate);
  $("rank-by").addEventListener("change", loadRank);
  $("rebuild-btn").addEventListener("click", rebuild);

  initRouter();
}

main().catch((e) => toast("初始化失败：" + (e.message || e), true));
