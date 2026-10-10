'use strict';

// ===== 云函数：/api/health =====
// 作用：公网探活。打开地址能拿到 JSON，说明「域名 → HTTP 访问服务 → 云函数」这条链路是通的。

const SERVICE_NAME = 'group-reminder';
const FN_NAME = 'api-health';
const VERSION = '1.0.0';

// 把对象打包成 HTTP 响应：状态码 + 响应头 + JSON 字符串
function json(statusCode, payload) {
  return {
    statusCode: statusCode,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload)
  };
}

exports.main = async (event, context) => {
  // event 由平台传入：HTTP 访问服务触发时，里面带着请求方法、路径、查询参数等
  const safeEvent = event || {};
  const safeContext = context || {};

  const method = String(safeEvent.httpMethod || 'GET').toUpperCase();
  // env 由平台运行时注入，不写死在代码里：它本身就是「这到底是哪个环境」的证据
  const envId = process.env.TCB_ENV || safeContext.namespace || 'unknown';

  if (method !== 'GET') {
    return json(405, {
      ok: false,
      service: SERVICE_NAME,
      fn: FN_NAME,
      env: envId,
      error: 'METHOD_NOT_ALLOWED'
    });
  }

  return json(200, {
    ok: true,
    service: SERVICE_NAME,
    fn: FN_NAME,
    env: envId,
    version: VERSION,
    ts: new Date().toISOString()
  });
};
