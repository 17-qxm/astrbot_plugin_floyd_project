// 今日歌单 — 带封面缩略图（cover_url 直接 img，失败显示首字母色块）。

import { defineComponent, computed } from "../vue.js";
import { stats } from "../store.js";

export const TodayList = defineComponent({
  name: "TodayList",
  setup() {
    // today.checkins 是 { uid: info }，转成数组并按时间排序。
    const items = computed(() => {
      const c = stats.today?.checkins || {};
      return Object.entries(c)
        .map(([uid, info]) => ({ uid, ...info }))
        .sort((a, b) => (a.time || "99:99").localeCompare(b.time || "99:99"));
    });
    return { stats, items };
  },
  template: `
    <div class="card">
      <div class="card-title">今日歌单</div>
      <div v-if="stats.errors.today" class="err-block">
        {{ stats.errors.today }}
      </div>
      <div v-else-if="!stats.today" style="padding:8px 0;">
        <div class="skeleton skel-line"></div>
        <div class="skeleton skel-line"></div>
      </div>
      <div v-else-if="items.length" class="today-grid">
        <div v-for="it in items" :key="it.uid" class="today-card">
          <img v-if="it.cover_url" class="cover" :src="it.cover_url"
            @error="$event.target.style.display='none';$event.target.nextElement.style.display='flex'" />
          <div v-else class="cover-fallback" style="display:flex;">🎵</div>
          <div class="cover-fallback" style="display:none;">🎵</div>
          <div class="info">
            <div class="song">{{ it.song || '?' }}</div>
            <div class="artist">{{ it.artist || '' }}</div>
            <div class="meta">{{ it.name || it.uid }} · {{ it.time || '' }}</div>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">今天还没有人打卡 🎵<br/>快来分享第一首歌！</div>
    </div>
  `,
});
