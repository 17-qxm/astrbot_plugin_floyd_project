// Vue 3 re-export。
// 依赖 index.html 里的 importmap 把 "vue" 映射到 CDN。
// 所有组件用 import { ref } from "./vue.js" 引用，统一入口。
// 离线/自托管场景：把下面 from 的 "vue" 改成本地文件路径，或改 importmap 指向本地。

export * from "vue";
