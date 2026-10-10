'use strict';

// ==========================================================================
// 云函数：api-inbox —— GET /api/inbox（Day 17）
// --------------------------------------------------------------------------
// 返回群消息原文列表（收件箱页面用），每条附带它的判定结果。
//
// ★ 这里用「嵌入」而不是 SQL 的 LEFT JOIN，但语义是一样的：
//   只取 messages（主表），判定结果作为附加字段一起带出来。
//   如果一条消息还没被判定过，reminders 就是空数组/null，它照样出现在列表里 ——
//   把「还没处理」误当成「不存在」是最容易犯的错。
// ==========================================================================

const { rdbGet, readLimit, json, iso, base, envId, dbError } = require('../_shared/db');

const FN_NAME = 'api-inbox';

const SELECT = 'id,group_name,sender,content,received_at,parse_status,reminders(importance,summary)';

exports.main = async (event, context) => {
  const safeEvent = event || {};
  const env = envId(context);
  const info = base(env, FN_NAME);

  const method = String(safeEvent.httpMethod || 'GET').toUpperCase();
  if (method !== 'GET') {
    return json(405, Object.assign({}, info, { ok: false, error: 'METHOD_NOT_ALLOWED' }));
  }

  const limit = readLimit((safeEvent.queryStringParameters || {}).limit);

  try {
    const rows = await rdbGet('messages', {
      select: SELECT,
      order: 'received_at.desc',
      limit: String(limit)
    }, env);

    const data = rows.map((m) => {
      const r = Array.isArray(m.reminders) ? m.reminders[0] : m.reminders;
      return {
        id: m.id,
        group_name: m.group_name,
        sender: m.sender,
        content: m.content,
        received_at: iso(m.received_at),
        parse_status: m.parse_status,
        // 还没判定过的消息，这里是 null —— 前端要能处理这种情况
        importance: r ? r.importance : null
      };
    });

    return json(200, Object.assign({}, info, { ok: true, count: data.length, data: data }));
  } catch (err) {
    return json(500, Object.assign({}, info, dbError(err)));
  }
};
