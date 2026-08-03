// 数据视图 — 总览卡片 + 热力图 + 排行榜 + 今日歌单，四合一页。

import { defineComponent, onMounted } from "../vue.js";
import { stats, loadStats } from "../store.js";
import { Heatmap } from "./Heatmap.js";
import { RankTable } from "./RankTable.js";
import { TodayList } from "./TodayList.js";

export const DataView = defineComponent({
  name: "DataView",
  components: { Heatmap, RankTable, TodayList },
  setup() {
    onMounted(() => loadStats());
    async function refresh() { await loadStats(true); }
    return { stats, refresh };
  },
  template: `
    <div>
      <!-- 总览卡片 -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title">
          <span>总览</span>
          <button class="ghost sm" @click="refresh">↻ 刷新</button>
        </div>
        <div v-if="stats.errors.overview" class="err-block">{{ stats.errors.overview }}</div>
        <div v-else-if="!stats.overview" class="stat-grid">
          <div class="stat" v-for="i in 4" :key="i">
            <div class="skeleton" style="width:60px;height:26px;"></div>
            <div class="skeleton" style="width:50px;height:12px;margin-top:6px;"></div>
          </div>
        </div>
        <div v-else class="stat-grid">
          <div class="stat">
            <div class="val accent">{{ stats.overview.total }}</div>
            <div class="lbl">累计总打卡</div>
          </div>
          <div class="stat">
            <div class="val">{{ stats.overview.users }}</div>
            <div class="lbl">参与人数</div>
          </div>
          <div class="stat">
            <div class="val">{{ stats.overview.today }}</div>
            <div class="lbl">今日打卡</div>
          </div>
          <div class="stat">
            <div class="val">{{ stats.overview.maxStreak }}</div>
            <div class="lbl">最长连续(天)</div>
          </div>
        </div>
      </div>

      <!-- 热力图 -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title">
          <span>打卡热力图（近 90 天）</span>
        </div>
        <div class="card-desc">颜色越深表示当日打卡人数越多。</div>
        <div v-if="stats.errors.heatmap" class="err-block">
          {{ stats.errors.heatmap }}
        </div>
        <div v-else-if="!stats.heatmap" style="height:60px;">
          <div class="skeleton" style="width:100%;height:60px;"></div>
        </div>
        <Heatmap v-else :days="stats.heatmap.days" />
      </div>

      <!-- 排行榜 + 今日歌单 -->
      <RankTable />
      <div style="margin-top:16px;">
        <TodayList />
      </div>
    </div>
  `,
});
