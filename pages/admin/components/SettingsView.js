// 设置视图（第三个 tab）— 插件配置表单 + 状态 JSON + 重算统计 + 说明。
// 配置写入后端 save_config_async，不自动 reload；提示用户去 Dashboard 重载。

import { defineComponent, ref, onMounted, inject } from "../vue.js";
import * as api from "../api.js";
import { state } from "../store.js";

export const SettingsView = defineComponent({
  name: "SettingsView",
  setup() {
    const toast = inject("toast");
    const confirm = inject("confirm");

    const schema = ref(null);
    const values = ref({});
    const draft = ref({});       // 编辑中的值
    const dirty = ref(false);
    const saving = ref(false);
    const stateText = ref("加载中…");

    onMounted(async () => {
      await loadConfig();
      await loadStateText();
    });

    async function loadConfig() {
      try {
        const d = await api.api("GET", "config");
        schema.value = d.schema || {};
        values.value = d.values || {};
        draft.value = JSON.parse(JSON.stringify(d.values || {}));
        dirty.value = false;
      } catch (e) {
        toast.error("加载配置失败：" + e.message);
      }
    }

    async function loadStateText() {
      try {
        const d = await api.api("GET", "state");
        stateText.value = JSON.stringify(d, null, 2);
      } catch (e) {
        stateText.value = "加载失败：" + e.message;
      }
    }

    function onInput(key, v) {
      draft.value[key] = v;
      dirty.value = JSON.stringify(draft.value) !== JSON.stringify(values.value);
    }

    // list 类型字段：增删群号（inline 输入器，见 template）。
    const newGroup = ref("");
    function commitGroup() {
      const g = String(newGroup.value || "").trim();
      if (!g) return;
      const arr = Array.isArray(draft.value.target_groups) ? [...draft.value.target_groups] : [];
      if (!arr.includes(g)) arr.push(g);
      onInput("target_groups", arr);
      newGroup.value = "";
    }
    function removeGroup(g) {
      const arr = (draft.value.target_groups || []).filter((x) => x !== g);
      onInput("target_groups", arr);
    }

    async function save() {
      if (!dirty.value) return;
      saving.value = true;
      try {
        const patch = {};
        for (const k of Object.keys(schema.value || {})) {
          if (JSON.stringify(draft.value[k]) !== JSON.stringify(values.value[k])) {
            patch[k] = draft.value[k];
          }
        }
        if (!Object.keys(patch).length) { toast.info("无变更"); saving.value = false; return; }
        const res = await api.api("POST", "config", patch);
        toast.success("配置已保存：" + res.saved.join(", "));
        if (res.hint) toast.info(res.hint, 6000);
        values.value = JSON.parse(JSON.stringify(draft.value));
        dirty.value = false;
      } catch (e) {
        toast.error("保存失败：" + e.message);
      } finally {
        saving.value = false;
      }
    }

    function reset() { draft.value = JSON.parse(JSON.stringify(values.value)); dirty.value = false; }

    async function rebuild() {
      const ok = await confirm("重算统计？", "根据全部历史打卡记录重新计算所有人的统计（总次数 / 连续天数）。\n这会覆盖现有 stats，不可撤销。");
      if (!ok) return;
      try {
        const data = await api.api("POST", "checkin/rebuild");
        toast.success(`已重算，覆盖 ${data.users} 位用户`);
        await loadStateText();
      } catch (e) {
        toast.error("重算失败：" + e.message);
      }
    }

    return {
      schema, draft, dirty, saving, stateText, newGroup,
      onInput, commitGroup, removeGroup, save, reset, rebuild, loadConfig,
    };
  },
  template: `
    <div>
      <!-- 配置表单 -->
      <div class="card">
        <div class="card-title">
          <span>插件配置</span>
          <span v-if="dirty" class="tag import">未保存</span>
        </div>
        <div v-if="!schema" class="skeleton skel-line"></div>
        <div v-else class="config-form">
          <!-- target_groups -->
          <div class="cfg-field" v-if="schema.target_groups">
            <label>{{ schema.target_groups.description }}</label>
            <div class="cfg-tags">
              <span v-for="g in (draft.target_groups || [])" :key="g" class="cfg-tag">
                {{ g }} <button class="ghost sm" @click="removeGroup(g)">✕</button>
              </span>
              <input v-model="newGroup" type="text" placeholder="群号…" @keydown.enter="commitGroup" style="flex:0 0 140px;" />
              <button class="sm" @click="commitGroup">添加</button>
            </div>
            <div class="cfg-hint">{{ schema.target_groups.hint }}</div>
          </div>

          <!-- push_time / summary_time / weekly_time -->
          <div class="cfg-field" v-if="schema.push_time">
            <label>{{ schema.push_time.description }}</label>
            <input type="time" :value="draft.push_time" @input="onInput('push_time', $event.target.value)" style="flex:0 0 140px;" />
          </div>
          <div class="cfg-field" v-if="schema.summary_time">
            <label>{{ schema.summary_time.description }}</label>
            <input type="time" :value="draft.summary_time" @input="onInput('summary_time', $event.target.value)" style="flex:0 0 140px;" />
          </div>
          <div class="cfg-field" v-if="schema.weekly_time">
            <label>{{ schema.weekly_time.description }}</label>
            <input type="time" :value="draft.weekly_time" @input="onInput('weekly_time', $event.target.value)" style="flex:0 0 140px;" />
          </div>

          <!-- weekly_day -->
          <div class="cfg-field" v-if="schema.weekly_day">
            <label>{{ schema.weekly_day.description }}</label>
            <select :value="draft.weekly_day" @change="onInput('weekly_day', Number($event.target.value))" style="flex:0 0 140px;">
              <option v-for="n in 7" :key="n" :value="n">{{ ['','周一','周二','周三','周四','周五','周六','周日'][n] }}</option>
            </select>
          </div>

          <!-- challenge_mode -->
          <div class="cfg-field" v-if="schema.challenge_mode">
            <label>{{ schema.challenge_mode.description }}</label>
            <select :value="draft.challenge_mode" @change="onInput('challenge_mode', $event.target.value)" style="flex:0 0 180px;">
              <option v-for="o in (schema.challenge_mode.options || [])" :key="o" :value="o">{{ o === 'sequential' ? 'sequential（顺序轮播）' : o + '（每日 AI）' }}</option>
            </select>
          </div>

          <!-- challenge_start_date -->
          <div class="cfg-field" v-if="schema.challenge_start_date">
            <label>{{ schema.challenge_start_date.description }}</label>
            <input type="date" :value="draft.challenge_start_date" @input="onInput('challenge_start_date', $event.target.value)" style="flex:0 0 180px;" />
          </div>

          <!-- auto_summary_image -->
          <div class="cfg-field" v-if="schema.auto_summary_image">
            <label>{{ schema.auto_summary_image.description }}</label>
            <label class="switch">
              <input type="checkbox" :checked="draft.auto_summary_image" @change="onInput('auto_summary_image', $event.target.checked)" />
              <span>{{ draft.auto_summary_image ? '开启' : '关闭' }}</span>
            </label>
            <div class="cfg-hint">{{ schema.auto_summary_image.hint }}</div>
          </div>
        </div>

        <div class="btn-group" style="margin-top:16px;">
          <button class="primary" :disabled="!dirty || saving" @click="save">
            <span v-if="saving" class="spinner"></span>
            {{ saving ? '保存中…' : '保存配置' }}
          </button>
          <button :disabled="!dirty" @click="reset">放弃</button>
        </div>
        <div class="cfg-hint" style="margin-top:8px;color:var(--warning);">
          ⚠ 定时任务类配置（推歌/总结时间、目标群）需在 Dashboard 重载插件后生效。
        </div>
      </div>

      <!-- 状态 + 重算 -->
      <div class="card">
        <div class="card-title">
          <span>插件状态</span>
          <button class="danger sm" @click="rebuild">重算统计</button>
        </div>
        <pre>{{ stateText }}</pre>
      </div>

      <!-- 说明 -->
      <div class="card">
        <div class="card-title">说明</div>
        <p class="muted" style="font-size:12px;line-height:1.7;">
          · 打卡规则：在打卡群发网易云分享并成功生成卡片，即记为当天一次（每人每天最多 1 次）。<br/>
          · UMO 捕获：定时推送需插件先「见过」目标群消息，在目标群发任意消息即可。<br/>
          · 文案来源：手动 / 导入 / AI。<br/>
          · 配置写入 data/config/ 下的 json，重载插件后定时任务按新配置重建。
        </p>
      </div>
    </div>
  `,
});

