// 确认模态 — 替代原生 confirm()。
// 用法：const confirm = inject('confirm'); if (await confirm('删除？','确定删吗')) {...}

import { reactive } from "../vue.js";

const current = reactive({ show: false, title: "", body: "", resolve: null });

export function confirm(title, body = "") {
  return new Promise((resolve) => {
    current.title = title;
    current.body = body;
    current.resolve = resolve;
    current.show = true;
  });
}

function _settle(ok) {
  if (current.resolve) current.resolve(ok);
  current.show = false;
  current.resolve = null;
}

export const ModalHost = {
  name: "ModalHost",
  setup() {
    return { current, ok: () => _settle(true), cancel: () => _settle(false) };
  },
  template: `
    <div v-if="current.show" class="modal-mask" @click.self="cancel">
      <div class="modal" @click.stop>
        <h3>{{ current.title }}</h3>
        <p v-if="current.body" style="white-space: pre-wrap;">{{ current.body }}</p>
        <div class="modal-acts">
          <button @click="cancel">取消</button>
          <button class="primary" @click="ok">确认</button>
        </div>
      </div>
    </div>
  `,
};
