'use strict';

// ==========================================================================
// _shared/db.js —— 两个读接口共用的数据访问层（Day 17）
// --------------------------------------------------------------------------
// ★ 为什么不用 pg 直连？
//   官方文档说云函数可以用 PostgreSQL 协议直连（PGHOST/PGUSER/PGPASSWORD…），
//   但实测在**免费体验版环境下这条路走不通**：云函数连内网地址
//   29.104.9.68:50331 会一直等到超时（Connection terminated due to
//   connection timeout）。社区 issue 也印证：个人版/体验版不开放内网互联。
//
// ★ 那用什么？
//   官方推荐的另一条路：CloudBase HTTP API（底层是 PostgREST），
//   走公网网关 https://<envId>.api.tcloudbasegateway.com，
//   鉴权用「服务端 API Key」。三个好处：
//     1) 不依赖内网，免费版可用
//     2) 零依赖，Node 自带 fetch 就行（云函数不需要装任何包）
//     3) 不用数据库密码，API Key 可单独吊销
//
// ★ 安全约定：
//   API Key 放环境变量（不进代码、不进仓库）；错误信息脱敏后才回给公网，
//   避免把凭据连同连接串一起泄露出去。
// ==========================================================================

const SERVICE_NAME = 'group-reminder';
const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

// 网关域名：国内地域固定 <envId>.api.tcloudbasegateway.com
function gateway(envId) {
  return `https://${envId}.api.tcloudbasegateway.com`;
}

function getPool() {
  throw new Error('pg 直连在当前环境不可用，已切换到 CloudBase HTTP API');
}

function readLimit(raw) {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_LIMIT;
  return Math.min(Math.floor(n), MAX_LIMIT);
}

function json(statusCode, payload) {
  return {
    statusCode: statusCode,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload)
  };
}

function iso(v) {
  if (v === null || v === undefined) return null;
  if (v instanceof Date) return v.toISOString();
  return new Date(v).toISOString();
}

function base(envId, fnName) {
  return { service: SERVICE_NAME, fn: fnName, env: envId };
}

function envId(context) {
  return process.env.TCB_ENV || (context && context.namespace) || 'unknown';
}

// 错误信息脱敏：把「://」到「@」之间的凭据整段替换掉
function sanitize(msg) {
  return String(msg || '')
    .replace(/:\/\/[^@\s]*@/g, '://***@')
    .replace(/(Bearer\s+)[A-Za-z0-9._-]{8,}/g, '$1***')
    .slice(0, 160);
}

function dbError(err) {
  return {
    ok: false,
    error: 'DB_UNAVAILABLE',
    code: String((err && err.code) || 'UNKNOWN').slice(0, 40),
    message: sanitize(err && err.message),
    hint: '检查云函数环境变量 DB_API_KEY 是否已配置（控制台：环境管理 → API Key 配置 → 服务端 API Key）'
  };
}

/**
 * 调 CloudBase HTTP API 查表。
 * @param {string} table   表名
 * @param {object} query   PostgREST 查询参数（select / 过滤 / order / limit）
 * @param {string} envId   环境 ID
 * @returns {Promise<Array>} 行数组
 */
async function rdbGet(table, query, envId) {
  const key = process.env.DB_API_KEY;
  if (!key) {
    const e = new Error('DB_API_KEY is not configured');
    e.code = 'NO_API_KEY';
    throw e;
  }

  const qs = Object.keys(query)
    .filter((k) => query[k] !== undefined && query[k] !== null)
    .map((k) => `${k}=${encodeURIComponent(query[k])}`)
    .join('&');

  const url = `${gateway(envId)}/v1/rdb/rest/${table}?${qs}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' },
    timeout: 15000
  });

  const text = await res.text();
  if (!res.ok) {
    const e = new Error(`HTTP ${res.status}: ${text}`);
    e.code = `HTTP_${res.status}`;
    throw e;
  }
  return JSON.parse(text);
}

module.exports = {
  getPool,
  rdbGet,
  gateway,
  readLimit,
  json,
  iso,
  base,
  envId,
  sanitize,
  dbError,
  DEFAULT_LIMIT
};
