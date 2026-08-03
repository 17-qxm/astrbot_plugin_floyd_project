// bridge 封装 — 统一错误处理，统一返回 {ok, data} 解包。
// 依赖 window.AstrBotPluginPage（AstrBot 注入），dev-mock.js 提供本地假实现。

const bridge = () => window.AstrBotPluginPage;

export function ready() {
  return bridge().ready();
}

// 统一 API 调用。返回解包后的 data；失败抛 Error（调用方自行 toast）。
// 注意：bridge endpoint 不能含 query string，GET 查询参数走 params（第二个参数）。
export async function api(method, endpoint, body) {
  const b = bridge();
  try {
    let r;
    if (method === "GET") {
      r = await b.apiGet(endpoint, body);
    } else {
      // DELETE / PUT 都走 apiPost（bridge 只有 apiGet/apiPost）。
      r = await b.apiPost(endpoint, body || {});
    }
    if (r && r.ok === false) {
      throw new Error(r.error || "请求失败");
    }
    return r && r.data !== undefined ? r.data : r;
  } catch (e) {
    const msg = (e && (e.message || e.statusText)) || String(e);
    throw new Error(msg);
  }
}

// 文件下载（走 bridge.download，触发浏览器下载）。
export async function download(endpoint, params = {}, filename) {
  return bridge().download(endpoint, params, filename);
}

// 文件上传（走 bridge.upload，multipart/form-data，字段名 file）。
export async function upload(endpoint, file) {
  return bridge().upload(endpoint, file);
}

// SSE 订阅封装。返回 subscriptionId。handlers: {onMessage, onError, onOpen}。
// 第三批 AI 流式生成用；第一批用不到，但先放这。
export async function subscribeSSE(endpoint, handlers, params) {
  return bridge().subscribeSSE(endpoint, handlers, params);
}

export async function unsubscribeSSE(id) {
  return bridge().unsubscribeSSE(id);
}

// 探测 bridge 是否支持 SSE（老版本 AstrBot 没有 subscribeSSE）。
export function sseSupported() {
  return typeof bridge().subscribeSSE === "function";
}

export function getContext() {
  return bridge().getContext?.() || {};
}
