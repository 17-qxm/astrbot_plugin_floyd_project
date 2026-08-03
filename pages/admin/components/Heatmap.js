// GitHub 式热力图矩阵 — 7 行(周一~周日) × N 列(周)。
// 鼠标悬停显示「日期：N 人」。月份标签在顶部。

import { defineComponent, computed } from "../vue.js";

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function level(n, max) {
  if (!n) return 0;
  return Math.min(4, Math.ceil((n / max) * 4));
}

export const Heatmap = defineComponent({
  name: "Heatmap",
  props: {
    days: { type: Object, required: true }, // { "YYYY-MM-DD": [uids] }
  },
  setup(props) {
    // 把 {date: [uids]} 转成按周排列的矩阵 + 月份标签。
    const matrix = computed(() => {
      const entries = Object.entries(props.days || {}).sort((a, b) => a[0].localeCompare(b[0]));
      if (!entries.length) return { weeks: [], months: [], max: 1 };

      const max = Math.max(1, ...entries.map(([, arr]) => (arr || []).length));

      // 按日期分组到周（ISO 周一为起始）。
      const weeks = []; // 每周 7 个格子（null 补位）
      const months = []; // {label, weekIndex} 月份标签
      let curWeek = new Array(7).fill(null);
      let curWeekIdx = 0;
      let lastMonth = -1;

      entries.forEach(([dateStr, arr]) => {
        const d = new Date(dateStr + "T00:00:00");
        // getDay: 0=周日...6=周六；转成 0=周一...6=周日。
        const dow = (d.getDay() + 6) % 7;
        const month = d.getMonth();
        if (dow === 0 && weeks.length > 0) {
          // 新的一周（除非是第一周）。
          weeks.push(curWeek);
          curWeek = new Array(7).fill(null);
          curWeekIdx++;
        }
        curWeek[dow] = { date: dateStr, count: (arr || []).length, level: level((arr || []).length, max) };
        if (month !== lastMonth) {
          months.push({ label: `${month + 1}月`, weekIndex: curWeekIdx });
          lastMonth = month;
        }
      });
      if (curWeek.some((x) => x !== null)) weeks.push(curWeek);

      return { weeks, months, max };
    });

    function tooltip(cell) {
      if (!cell) return "";
      return `${cell.date}：${cell.count} 人`;
    }

    return { matrix, WEEKDAYS, tooltip };
  },
  template: `
    <div>
      <div class="heatmap-wrap">
        <!-- 月份标签行 -->
        <div class="heat-months">
          <template v-for="(m, i) in matrix.months" :key="i">
            <span :style="{ gridColumn: (m.weekIndex + 1) }">{{ m.label }}</span>
          </template>
        </div>
        <div style="display:flex;gap:4px;">
          <!-- 星期标签列 -->
          <div style="display:grid;grid-template-rows:repeat(7,12px);gap:3px;font-size:10px;color:var(--text-faint);padding-top:0;">
            <span v-for="(w, i) in WEEKDAYS" :key="i" style="height:12px;display:flex;align-items:center;">{{ i % 2 === 0 ? w : '' }}</span>
          </div>
          <!-- 热力格 -->
          <div class="heatmap">
            <template v-for="(week, wi) in matrix.weeks" :key="wi">
              <div v-for="(cell, di) in week" :key="di"
                :class="['heat-cell', cell ? 'l' + cell.level : '']"
                :title="tooltip(cell)">
              </div>
            </template>
          </div>
        </div>
      </div>
      <div class="heat-legend">
        <span>少</span>
        <div class="swatches">
          <span style="background:var(--surface-2);border:1px solid var(--border-soft);"></span>
          <span style="background:#1e2331;"></span>
          <span style="background:#44376b;"></span>
          <span style="background:#7c3aed;"></span>
          <span style="background:#a78bfa;"></span>
        </div>
        <span>多</span>
      </div>
    </div>
  `,
});
