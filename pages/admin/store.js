// 响应式数据 store — 缓存 + stale-while-revalidate。
// 首次加载后缓存，切 tab 回来秒显缓存，后台静默刷新。
// 任一接口失败不阻塞其他（调用方用 allSettled）。

import { reactive } from "./vue.js";
import * as api from "./api.js";

// 全局状态（顶栏状态条用）。
export const state = reactive({
  challengeCount: null,   // null = 未加载
  challengeMode: "",
  pushTime: "",
  summaryTime: "",
  weeklyTime: "",
  weeklyDay: 7,
  startDate: "",          // challenge_start_date，预览计算用
  autoSummaryImage: true,
  todayCount: null,
  serverTime: "",
  loaded: false,
});

// 文案库。
export const challenges = reactive({
  list: null,             // null = 未加载，[] = 空
  loading: false,
  error: null,
  fetchedAt: 0,
});

// 统计相关。
export const stats = reactive({
  overview: null,         // {total, users, today, maxStreak}
  heatmap: null,          // {days: {date: [uids]}}
  rank: null,             // {by, rank: [...]}
  today: null,            // {date, checkins: {uid: info}}
  loading: false,
  errors: {},             // {overview: msg, heatmap: msg, ...}
  fetchedAt: 0,
});

// ---------- 全局状态 ----------
const STALE_STATE = 30000; // 30s 内不重复拉 state
export async function loadState(force = false) {
  if (!force && Date.now() - (state._t || 0) < STALE_STATE) return;
  try {
    const d = await api.api("GET", "state");
    state.challengeCount = d.challenge_count;
    state.challengeMode = d.challenge_mode;
    state.pushTime = d.push_time;
    state.summaryTime = d.summary_time;
    state.weeklyTime = d.weekly_time;
    state.weeklyDay = d.weekly_day;
    state.startDate = d.challenge_start_date;
    state.autoSummaryImage = d.auto_summary_image;
    state.serverTime = d.server_time;
    state.loaded = true;
    state._t = Date.now();
    // state 不含 todayCount，单独拉 today 接口补。
    refreshTodayCount();
  } catch (e) {
    // state 失败不 toast，静默；顶栏显示 -。
  }
}

async function refreshTodayCount() {
  try {
    const t = await api.api("GET", "checkin/today");
    state.todayCount = Object.keys(t.checkins || {}).length;
  } catch (e) { /* 静默 */ }
}

// ---------- 文案库 ----------
export async function loadChallenges(force = false) {
  if (!force && challenges.list && Date.now() - challenges.fetchedAt < 5000) {
    return challenges.list;
  }
  challenges.loading = true;
  challenges.error = null;
  try {
    const data = await api.api("GET", "challenges");
    challenges.list = data;
    challenges.fetchedAt = Date.now();
    // 同步刷新顶栏计数。
    state.challengeCount = data.length;
  } catch (e) {
    challenges.error = e.message;
    throw e;
  } finally {
    challenges.loading = false;
  }
}

// 后台静默刷新（不转 loading，不报错）。
export async function refreshChallenges() {
  try {
    const data = await api.api("GET", "challenges");
    challenges.list = data;
    challenges.fetchedAt = Date.now();
    state.challengeCount = data.length;
  } catch (e) { /* 静默 */ }
}

// ---------- 统计（4 个请求并发，allSettled 互不阻塞） ----------
const STALE_STATS = 30000;
export async function loadStats(force = false) {
  if (!force && stats.overview && Date.now() - stats.fetchedAt < STALE_STATS) {
    return;
  }
  stats.loading = true;
  stats.errors = {};
  const results = await Promise.allSettled([
    api.api("GET", "checkin/stats"),
    api.api("GET", "checkin/today"),
    api.api("GET", "checkin/history"),
    api.api("GET", "checkin/rank", { by: "total", limit: 20 }),
  ]);
  const [rStats, rToday, rHeat, rRank] = results;

  if (rStats.status === "fulfilled") {
    const users = rStats.value.users || {};
    const vals = Object.values(users);
    stats.overview = {
      total: vals.reduce((s, u) => s + (u.total || 0), 0),
      users: Object.keys(users).length,
      today: 0, // 下面用 rToday 填
      maxStreak: vals.reduce((s, u) => Math.max(s, u.max_streak || 0), 0),
    };
  } else {
    stats.errors.overview = rStats.reason?.message || "失败";
  }

  if (rToday.status === "fulfilled") {
    stats.today = rToday.value;
    const n = Object.keys(rToday.value.checkins || {}).length;
    if (stats.overview) stats.overview.today = n;
    state.todayCount = n;
  } else {
    stats.errors.today = rToday.reason?.message || "失败";
  }

  if (rHeat.status === "fulfilled") {
    stats.heatmap = rHeat.value;
  } else {
    stats.errors.heatmap = rHeat.reason?.message || "失败";
  }

  if (rRank.status === "fulfilled") {
    stats.rank = rRank.value;
  } else {
    stats.errors.rank = rRank.reason?.message || "失败";
  }

  stats.fetchedAt = Date.now();
  stats.loading = false;
}

// 排行榜单独刷新（切换排序维度时只刷这一项）。
export async function loadRank(by) {
  try {
    const data = await api.api("GET", "checkin/rank", { by, limit: 20 });
    stats.rank = data;
    delete stats.errors.rank;
  } catch (e) {
    stats.errors.rank = e.message;
    throw e;
  }
}

// ---------- 预览计算（纯函数，不请求网络） ----------
// 根据 startDate + 文案库长度，计算某天对应第几条文案。
// 与后端 challenge.py 的 get_challenge_for_date 逻辑一致：
//   day_number = (date - start_date).days + 1；列表耗尽循环取模。

const WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

function parseDate(s) {
  // "YYYY-MM-DD" -> Date(本地)。容错：非法返回 null。
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return isNaN(d.getTime()) ? null : d;
}
function isoDate(d) {
  // Date -> "YYYY-MM-DD"（本地时区）。
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// 今日预览：返回 { dayNumber, item } 或 { dayNumber: null, item: null }（未到起算日/空库）。
export function todayPreview(list) {
  if (!list || !list.length) return { dayNumber: null, item: null, reason: "文案库为空" };
  const start = parseDate(state.startDate);
  if (!start) return { dayNumber: null, item: null, reason: "未配置起算日" };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (today < start) return { dayNumber: null, item: null, reason: "未到起算日" };
  const dayNumber = Math.floor((today - start) / 86400000) + 1;
  // list 是 list_all 返回，每项含 idx（1-based）；按列表顺序取模。
  const item = list[(dayNumber - 1) % list.length];
  return { dayNumber, item };
}

// 排期预览：从今天起未来 days 天（含今天），每天对应哪条文案。
// 返回 [{ date, weekday, dayNumber, item }]。
export function schedulePreview(list, days = 7) {
  if (!list || !list.length) return [];
  const start = parseDate(state.startDate);
  if (!start) return [];
  const out = [];
  const base = new Date();
  base.setHours(0, 0, 0, 0);
  for (let i = 0; i < days; i++) {
    const d = new Date(base);
    d.setDate(d.getDate() + i);
    if (d < start) {
      out.push({ date: isoDate(d), weekday: WEEKDAY_ZH[(d.getDay() + 6) % 7], dayNumber: null, item: null });
      continue;
    }
    const dayNumber = Math.floor((d - start) / 86400000) + 1;
    const item = list[(dayNumber - 1) % list.length];
    out.push({ date: isoDate(d), weekday: WEEKDAY_ZH[(d.getDay() + 6) % 7], dayNumber, item });
  }
  return out;
}

