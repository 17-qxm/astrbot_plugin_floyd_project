// 本地预览用假 bridge —— 通过 <script src> 无条件加载，内部自检 ?dev=1。
// 非 dev 模式立即 return，不注入任何东西，生产环境零影响。
// 用法：cd pages/admin && python -m http.server 8000，浏览器开 http://localhost:8000?dev=1

(function () {
  if (new URLSearchParams(location.search).get("dev") !== "1") return;
  const STORAGE_KEY = "floyd-mock-data";
  const today = () => new Date().toISOString().slice(0, 10);
  const isoDate = (d) => d.toISOString().slice(0, 10);

  // 内存数据（持久化到 localStorage，方便调试导入/配置改动）。
  // ?reset=1 时强制重新 seed；旧版数据（无 schema 字段）也会重新 seed。
  let data = (() => {
    if (new URLSearchParams(location.search).get("reset") === "1") return seed();
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && parsed.schema) return parsed;
      }
    } catch (e) {}
    return seed();
  })();
  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); } catch (e) {}
  }
  function seed() {
    const challenges = [];
    const samples = [
      "一首让你单曲循环的歌", "一首带「风」字的歌", "一首关于夏天的歌",
      "一首你会在深夜听的歌", "一首让你想起某个人的歌", "一首前奏一响就爱上的歌",
      "一首歌词写到你心里的歌", "一首你听过现场的歌", "一首老歌但不过时",
      "一首你推荐给所有人的歌", "一首副歌洗脑的歌", "一首纯音乐",
    ];
    samples.forEach((t, i) => {
      challenges.push({ idx: i + 1, text: t, source: i % 3 === 0 ? "ai" : i % 3 === 1 ? "import" : "manual" });
    });

    // 打卡数据：近 90 天随机。
    const byDate = {};
    const stats = {};
    const names = ["小明", "阿强", "阿珍", "老王", "阿May", "Tony", "小李"];
    for (let i = 89; i >= 0; i--) {
      const d = new Date(); d.setDate(d.getDate() - i);
      const ds = isoDate(d);
      byDate[ds] = {};
      const n = Math.random() < 0.3 ? 0 : Math.floor(Math.random() * 5) + 1;
      for (let j = 0; j < n; j++) {
        const uid = "1000" + j;
        const name = names[j % names.length];
        byDate[ds][uid] = {
          uid, name,
          song: `歌曲 ${j + 1}`,
          artist: `歌手 ${j}`,
          cover_url: "",
          time: `${String(8 + j).padStart(2, "0")}:${String(j * 7 % 60).padStart(2, "0")}`,
        };
      }
    }
    // 计算 stats。
    Object.entries(byDate).forEach(([ds, day]) => {
      Object.entries(day).forEach(([uid, info]) => {
        if (!stats[uid]) stats[uid] = { name: info.name, total: 0, streak: 0, max_streak: 0, last_date: null };
        const s = stats[uid];
        const prev = s.last_date ? new Date(s.last_date) : null;
        const cur = new Date(ds);
        if (prev && (cur - prev) / 86400000 === 1) s.streak += 1;
        else s.streak = 1;
        s.total += 1;
        s.max_streak = Math.max(s.max_streak, s.streak);
        s.last_date = ds;
      });
    });
    // 配置 schema（与 _conf_schema.json 对齐，供设置 tab 渲染表单）。
    const schema = {
      target_groups: { description: "目标群号", type: "list", items: { type: "string" }, hint: "既是打卡群也是推送目标", default: [] },
      push_time: { description: "每日推歌时间", type: "string", hint: "格式 HH:MM", default: "08:00" },
      summary_time: { description: "每日总结时间", type: "string", hint: "格式 HH:MM", default: "22:00" },
      weekly_time: { description: "每周总结时间", type: "string", hint: "格式 HH:MM", default: "22:30" },
      weekly_day: { description: "每周总结发送日", type: "int", hint: "1=周一...7=周日", default: 7 },
      challenge_mode: { description: "推歌文案来源模式", type: "string", hint: "sequential / daily_ai", default: "sequential", options: ["sequential", "daily_ai"] },
      challenge_start_date: { description: "推歌挑战 Day1 起算日期", type: "string", hint: "YYYY-MM-DD", default: "2026-04-13" },
      auto_summary_image: { description: "每日总结渲染为图片", type: "bool", hint: "关闭则发纯文本", default: true },
    };
    const start_date = "2026-04-13";
    const values = {
      target_groups: ["123456"],
      push_time: "08:00",
      summary_time: "22:00",
      weekly_time: "22:30",
      weekly_day: 7,
      challenge_mode: "sequential",
      challenge_start_date: start_date,
      auto_summary_image: true,
    };
    return { challenges, byDate, stats, schema, values, start_date };
  }

  function ok(d) { return { ok: true, data: d }; }
  function err(m, c) { return { ok: false, error: m, status: c || 400 }; }

  function delay(ms) { return new Promise((r) => setTimeout(r, ms || 200)); }

  function route(method, endpoint, body) {
    // challenges
    if (endpoint === "challenges" && method === "GET") {
      return ok(data.challenges);
    }
    if (endpoint === "challenges" && method === "POST") {
      if (body.idx != null) {
        const it = data.challenges.find((c) => c.idx === body.idx);
        if (!it) return err("idx 不存在", 404);
        it.text = body.text;
        save();
        return ok(it);
      }
      const idx = data.challenges.length + 1;
      const item = { idx, text: body.text, source: body.source || "manual" };
      data.challenges.push(item);
      save();
      return ok(item);
    }
    if (endpoint === "challenges/delete") {
      const i = data.challenges.findIndex((c) => c.idx === body.idx);
      if (i < 0) return err("idx 不存在", 404);
      data.challenges.splice(i, 1);
      data.challenges.forEach((c, k) => (c.idx = k + 1));
      save();
      return ok({ deleted: true });
    }
    if (endpoint === "challenges/import") {
      const texts = body.texts || (body.raw || "").splitlines ? (body.raw || "").split("\n") : [];
      const cleaned = texts.map((t) => t.trim()).filter(Boolean);
      if (body.mode === "replace") data.challenges = [];
      const before = data.challenges.length;
      cleaned.forEach((t, k) => {
        data.challenges.push({ idx: before + k + 1, text: t, source: "import" });
      });
      save();
      return ok({ affected: cleaned.length, total: data.challenges.length });
    }

    // checkin
    if (endpoint === "checkin/today") return ok({ date: today(), checkins: data.byDate[today()] || {} });
    if (endpoint === "checkin/stats") return ok({ users: data.stats });
    if (endpoint === "checkin/history") {
      // 真实后端 days[date] 是 uid 数组（list(day.keys())），mock 对齐。
      const days = {};
      Object.entries(data.byDate).forEach(([ds, day]) => { days[ds] = Object.keys(day); });
      return ok({ from: Object.keys(data.byDate)[0], to: today(), days });
    }
    if (endpoint === "checkin/rank") {
      const by = body.by || "total";
      const rank = Object.entries(data.stats).map(([uid, s]) => ({ user_id: uid, ...s }));
      rank.sort((a, b) => (b[by] || 0) - (a[by] || 0));
      return ok({ by, rank: rank.slice(0, body.limit || 20) });
    }
    if (endpoint === "checkin/rebuild") return ok({ users: Object.keys(data.stats).length });

    // state
    if (endpoint === "state") {
      return ok({
        challenge_count: data.challenges.length,
        challenge_mode: "sequential",
        push_time: "08:00",
        summary_time: "22:00",
        weekly_time: "22:30",
        weekly_day: 7,
        challenge_start_date: data.start_date || "2026-04-13",
        auto_summary_image: true,
        target_groups: ["123456"],
        server_time: new Date().toISOString().slice(0, 19),
      });
    }

    // config
    if (endpoint === "config" && method === "GET") {
      return ok({ schema: data.schema, values: data.values });
    }
    if (endpoint === "config" && method === "POST") {
      Object.entries(body).forEach(([k, v]) => { data.values[k] = v; });
      if (body.challenge_start_date) data.start_date = body.challenge_start_date;
      save();
      return ok({ saved: Object.keys(body), hint: "配置已写入（mock）。真实环境需在 Dashboard 重载插件" });
    }
    return err("未知 endpoint: " + endpoint, 404);
  }

  window.AstrBotPluginPage = {
    ready: async () => { await delay(100); },
    getContext: () => ({ isDark: true, locale: "zh" }),
    apiGet: async (endpoint, params) => { await delay(); return route("GET", endpoint, params || {}); },
    apiPost: async (endpoint, body) => { await delay(); return route("POST", endpoint, body || {}); },
    download: async (endpoint) => {
      if (endpoint === "challenges/export") {
        const text = data.challenges.map((c) => c.text).join("\n");
        const blob = new Blob([text], { type: "text/plain" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "challenges.txt";
        a.click();
      }
    },
    subscribeSSE: async (endpoint, handlers) => {
      console.log("[mock] subscribeSSE", endpoint);
      handlers.onOpen && handlers.onOpen();
      return "mock-sub";
    },
    unsubscribeSSE: async () => {},
  };

  console.log("%c[Floyd dev-mock] 假 bridge 已加载。数据持久化在 localStorage。清空：localStorage.removeItem('floyd-mock-data')", "color:#8b5cf6");
})();
