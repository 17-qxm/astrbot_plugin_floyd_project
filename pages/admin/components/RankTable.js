// 排行榜表格 — 前三名奖牌 + 头像（前端拼 q.qlogo.cn）。

import { defineComponent, ref, watch } from "../vue.js";
import { stats, loadRank } from "../store.js";
import { inject } from "../vue.js";

const MEDALS = ["🥇", "🥈", "🥉"];

function avatarUrl(uid) {
  if (!uid) return "";
  return `https://q.qlogo.cn/headimg_dl?dst_uin=${uid}&spec=640&img_type=jpg`;
}

export const RankTable = defineComponent({
  name: "RankTable",
  setup() {
    const toast = inject("toast");
    const by = ref("total");
    const loading = ref(false);

    async function change(val) {
      by.value = val;
      loading.value = true;
      try {
        await loadRank(val);
      } catch (e) {
        toast.error("加载排行失败：" + e.message);
      } finally {
        loading.value = false;
      }
    }

    return { stats, by, loading, change, MEDALS, avatarUrl };
  },
  template: `
    <div class="card">
      <div class="card-title">
        <span>排行榜</span>
        <select v-model="by" @change="change(by)" class="narrow" style="flex:0 0 120px;font-size:12px;">
          <option value="total">总打卡数</option>
          <option value="streak">当前连续</option>
          <option value="max_streak">最长连续</option>
        </select>
      </div>
      <div v-if="stats.errors.rank" class="err-block">
        {{ stats.errors.rank }}
        <div><button class="sm" @click="change(by)">重试</button></div>
      </div>
      <div v-else-if="!stats.rank" style="padding:8px 0;">
        <div class="skeleton skel-line"></div>
        <div class="skeleton skel-line"></div>
        <div class="skeleton skel-line"></div>
      </div>
      <table v-else-if="stats.rank.rank.length" class="rank-table">
        <thead>
          <tr><th class="pos">#</th><th>成员</th><th class="num">数值</th><th>上次打卡</th></tr>
        </thead>
        <tbody>
          <tr v-for="(u, i) in stats.rank.rank" :key="u.user_id">
            <td :class="['pos', { medal: i < 3 }]">{{ i < 3 ? MEDALS[i] : (i + 1) }}</td>
            <td>
              <div class="user">
                <img :src="avatarUrl(u.user_id)" @error="$event.target.style.display='none';$event.target.nextElement.style.display='flex'" />
                <span class="ava-fallback" style="display:none;">{{ (u.name || u.user_id || '?')[0] }}</span>
                <span>{{ u.name || u.user_id }}</span>
              </div>
            </td>
            <td class="num">{{ u[by] ?? 0 }}</td>
            <td class="faint">{{ u.last_date || '-' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">还没有打卡记录</div>
    </div>
  `,
});
