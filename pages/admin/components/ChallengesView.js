// 文案库视图 — 只读列表 + 导入(文本框/上传) + 导出 + 今日预览 + 排期预览。
// 编辑/删除/新增/AI 生成已移除（用户需求：只保留下载、上传、文本框上传、预览、今日预览）。

import { defineComponent, ref, computed, inject, onMounted } from "../vue.js";
import * as api from "../api.js";
import {
  challenges, loadChallenges, state,
  todayPreview, schedulePreview,
} from "../store.js";
import { SkeletonRows } from "./Skeleton.js";

const PAGE_SIZE = 50;
const SRC_LABEL = { manual: "手动", import: "导入", ai: "AI" };

export const ChallengesView = defineComponent({
  name: "ChallengesView",
  components: { SkeletonRows },
  setup() {
    const toast = inject("toast");

    onMounted(() => { loadChallenges().catch(() => {}); });

    const search = ref("");
    const srcFilter = ref("all");
    const page = ref(1);
    const showImport = ref(false);
    const importText = ref("");
    const importMode = ref("append");

    const filtered = computed(() => {
      const list = challenges.list || [];
      const q = search.value.trim().toLowerCase();
      return list.filter((it) => {
        if (srcFilter.value !== "all" && (it.source || "manual") !== srcFilter.value) return false;
        if (q && !(it.text || "").toLowerCase().includes(q)) return false;
        return true;
      });
    });

    const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)));
    const paged = computed(() => {
      const start = (page.value - 1) * PAGE_SIZE;
      return filtered.value.slice(start, start + PAGE_SIZE);
    });

    const today = computed(() => todayPreview(challenges.list || []));
    const schedule = computed(() => schedulePreview(challenges.list || [], 7));

    function resetPage() { page.value = 1; }

    async function reload() {
      try {
        await loadChallenges(true);
      } catch (e) {
        toast.error("加载文案失败：" + e.message);
      }
    }

    async function doImport() {
      const raw = importText.value;
      if (!raw.trim()) { toast.error("文本为空"); return; }
      try {
        const data = await api.api("POST", "challenges/import", { raw, mode: importMode.value });
        toast.success(`已${importMode.value === "replace" ? "覆盖" : "追加"} ${data.affected} 条，共 ${data.total} 条`);
        importText.value = "";
        showImport.value = false;
        await loadChallenges(true);
      } catch (e) {
        toast.error("导入失败：" + e.message);
      }
    }

    async function onUpload(ev) {
      const f = ev.target.files[0];
      if (!f) return;
      try {
        const text = await f.text();
        const data = await api.api("POST", "challenges/import", { raw: text, mode: importMode.value });
        toast.success(`已${importMode.value === "replace" ? "覆盖" : "追加"} ${data.affected} 条`);
        await loadChallenges(true);
      } catch (e) {
        toast.error("上传失败：" + e.message);
      }
      ev.target.value = "";
    }

    async function doExport() {
      try {
        await api.download("challenges/export", {}, "challenges.txt");
        toast.success("已导出");
      } catch (e) {
        toast.error("导出失败：" + (e.message || e));
      }
    }

    return {
      challenges, state, search, srcFilter, page, totalPages, paged,
      showImport, importText, importMode,
      filtered, today, schedule,
      resetPage, reload, doImport, onUpload, doExport,
      srcLabel: (s) => SRC_LABEL[s] || "手动",
    };
  },
  template: `
    <div>
      <!-- 今日预览 -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title">📌 今日预览</div>
        <div v-if="today.item" class="today-preview">
          <span class="day-num">Day {{ today.dayNumber }}</span>
          <span class="preview-text">{{ today.item.text }}</span>
        </div>
        <div v-else class="faint" style="font-size:13px;">{{ today.reason || '暂无今日文案' }}</div>
        <div class="faint" style="font-size:11px;margin-top:6px;">
          起算日：{{ state.startDate || '未配置' }} · 模式：{{ state.challengeMode }}
        </div>
      </div>

      <!-- 工具栏 -->
      <div class="toolbar">
        <button @click="showImport = !showImport">导入</button>
        <button @click="doExport">⬇ 导出</button>
        <div class="spacer"></div>
        <div class="search">
          <span class="ico">⌕</span>
          <input v-model="search" @input="resetPage" placeholder="搜索文案…" />
        </div>
        <select v-model="srcFilter" @change="resetPage" class="narrow" style="flex:0 0 110px;">
          <option value="all">全部来源</option>
          <option value="manual">手动</option>
          <option value="import">导入</option>
          <option value="ai">AI</option>
        </select>
      </div>

      <!-- 导入面板 -->
      <div v-if="showImport" class="card" style="margin-bottom:16px;">
        <div class="card-title">批量导入</div>
        <div class="row" style="margin-bottom:8px;">
          <label class="narrow" style="flex:0 0 auto;display:flex;align-items:center;gap:4px;">
            <input type="radio" v-model="importMode" value="append" /> 追加
          </label>
          <label class="narrow" style="flex:0 0 auto;display:flex;align-items:center;gap:4px;">
            <input type="radio" v-model="importMode" value="replace" /> 覆盖全部
          </label>
        </div>
        <textarea v-model="importText" placeholder="每行一条文案…"></textarea>
        <div class="btn-group" style="margin-top:8px;">
          <input type="file" accept=".txt" @change="onUpload" style="display:none;" ref="fileIn" />
          <button @click="$refs.fileIn.click()">⬆ 上传 .txt</button>
          <button class="primary" @click="doImport">导入文本框</button>
        </div>
      </div>

      <!-- 排期预览（未来 7 天） -->
      <div v-if="schedule.length" class="card" style="margin-bottom:16px;">
        <div class="card-title">📅 排期预览（未来 7 天）</div>
        <ul class="ch-list">
          <li v-for="s in schedule" :key="s.date" class="ch-row">
            <span class="idx">{{ s.weekday }}</span>
            <span class="faint" style="flex:0 0 90px;font-size:12px;">{{ s.date }}</span>
            <template v-if="s.item">
              <span class="faint" style="flex:0 0 auto;font-size:11px;">Day {{ s.dayNumber }}</span>
              <span class="text">{{ s.item.text }}</span>
            </template>
            <span v-else class="faint text">未到起算日</span>
          </li>
        </ul>
      </div>

      <!-- 文案库列表（只读） -->
      <div class="card" style="padding:0;">
        <div class="list-head" style="padding:12px 12px 8px;">
          <span>文案库（共 <b>{{ filtered.length }}</b> 条）</span>
        </div>
        <div v-if="challenges.list === null" style="padding:4px 0;">
          <SkeletonRows :rows="5" />
        </div>
        <div v-else-if="paged.length === 0" class="ch-empty">
          {{ (search || srcFilter !== 'all') ? '没有匹配的文案' : '文案库为空，点上方「导入」添加文案' }}
        </div>
        <ul v-else class="ch-list">
          <li v-for="item in paged" :key="item.idx" class="ch-row">
            <span class="idx">#{{ item.idx }}</span>
            <span class="text">{{ item.text }}</span>
            <span :class="['tag', 'src', item.source || 'manual']">{{ srcLabel(item.source) }}</span>
          </li>
        </ul>
      </div>

      <!-- 分页 -->
      <div v-if="filtered.length > 50" class="pager">
        <button class="sm" :disabled="page <= 1" @click="page--">‹ 上一页</button>
        <span class="info">{{ page }} / {{ totalPages }}</span>
        <button class="sm" :disabled="page >= totalPages" @click="page++">下一页 ›</button>
      </div>
    </div>
  `,
});
