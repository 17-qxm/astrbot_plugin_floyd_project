// Floyd 管理面板根组件 — Vue3 挂载。
// 顶栏(实时状态条) + 两个 tab(文案库/数据) + 设置抽屉 + Toast/Modal host。

import { createApp, reactive, ref, onMounted, provide } from "./vue.js";
import { ready } from "./api.js";
import { state, loadState } from "./store.js";
import { ChallengesView } from "./components/ChallengesView.js";
import { DataView } from "./components/DataView.js";
import { SettingsView } from "./components/SettingsView.js";
import { toast, ToastHost } from "./components/Toast.js";
import { confirm, ModalHost } from "./components/Modal.js";

const App = {
  name: "App",
  components: { ChallengesView, DataView, SettingsView, ToastHost, ModalHost },
  setup() {
    provide("toast", toast);
    provide("confirm", confirm);

    const tab = ref("challenges"); // challenges / data / settings

    function switchTab(name) { tab.value = name; }

    onMounted(async () => {
      try {
        await ready();
        await loadState();
        setInterval(() => loadState(), 30000);
      } catch (e) {
        toast.error("初始化失败：" + (e.message || String(e)), 8000);
      }
    });

    return { state, tab, switchTab };
  },
  template: `
    <div class="app">
      <!-- 顶栏 -->
      <div class="topbar">
        <div class="brand">
          <span class="logo">🎸</span>
          <span>Floyd</span>
        </div>
        <div class="state-bar">
          <span class="seg"><span class="dot"></span> 文案 <b>{{ state.challengeCount ?? '–' }}</b></span>
          <span class="seg" v-if="state.challengeMode">模式 <b>{{ state.challengeMode }}</b></span>
          <span class="seg">今日 <b>{{ state.todayCount ?? '–' }}</b></span>
        </div>
      </div>

      <!-- Tabs -->
      <div class="tabs">
        <button :class="['tab', { active: tab === 'challenges' }]" @click="switchTab('challenges')">文案库</button>
        <button :class="['tab', { active: tab === 'data' }]" @click="switchTab('data')">数据</button>
        <button :class="['tab', { active: tab === 'settings' }]" @click="switchTab('settings')">设置</button>
      </div>

      <!-- 视图 -->
      <ChallengesView v-if="tab === 'challenges'" />
      <DataView v-else-if="tab === 'data'" />
      <SettingsView v-else-if="tab === 'settings'" />

      <!-- Toast / Modal -->
      <ToastHost />
      <ModalHost />
    </div>
  `,
};

createApp(App).mount("#floyd-app");
