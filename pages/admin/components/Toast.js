// Toast 队列 — 多个 toast 堆叠不覆盖。provide/inject 注入。
// 用法：const toast = inject('toast'); toast.success('已保存'); toast.error('失败');

import { reactive } from "../vue.js";

const items = reactive([]);
let seq = 0;

function push(type, msg, ms = 2600) {
  const id = ++seq;
  items.push({ id, type, msg });
  if (ms > 0) setTimeout(() => dismiss(id), ms);
  return id;
}
function dismiss(id) {
  const i = items.findIndex((t) => t.id === id);
  if (i >= 0) items.splice(i, 1);
}

export const toast = {
  success: (m, ms) => push("success", m, ms),
  error: (m, ms) => push("error", m, ms ?? 4000),
  info: (m, ms) => push("info", m, ms),
  dismiss,
};

export const ToastHost = {
  name: "ToastHost",
  setup() {
    return { items };
  },
  template: `
    <div class="toast-stack">
      <div v-for="t in items" :key="t.id" :class="['toast', t.type]" @click="dismiss(t.id)">
        {{ t.msg }}
      </div>
    </div>
  `,
};
