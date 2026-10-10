'use strict';

// ==========================================================================
// 云函数：api-timeline —— GET /api/timeline（Day 17）
// --------------------------------------------------------------------------
// 返回 AI 判定为 important 的重要事项，就是前端时间线页面要显示的那批。
// 数据来自 CloudBase PostgreSQL（真库），经 HTTP API 读 reminders + messages。
//
// ★ 为什么单独一个函数、而不是一个函数里判断路径：
//   CloudBase「HTTP 访问服务」把请求转给事件函数时，event 里的 path 恒为 "/"
//   （实测：绑了 /api/timeline，event.path 仍然是 "/"）。没法靠 path 分流，
//   于是一个函数只干一件事，拆成 api-timeline / api-inbox 两个。
//
// ★ 字段名与前端 web/mock/index.html 的 MOCK_TIMELINE 逐字对应，
//   第 3 周只是换了数据来源，前端一行都不用改。
// ==========================================================================

const { rdbGet, readLimit, json, iso, base, envId, dbError } = require('../_shared/db');

const FN_NAME = 'api-timeline';

// PostgREST 的「嵌入」写法：reminders 通过外键 message_id 关联 messages，
// select 里写 messages(...) 就能一次把两张表的数据取回来，省掉手工拼 JOIN。
const SELECT = 'id,importance,summary,deadline,messages(id,group_name,sender,content,received_at)';

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
    const rows = await rdbGet('reminders', {
      select: SELECT,
      importance: 'eq.important',
      order: 'deadline.asc.nullslast,created_at.desc',
      limit: String(limit)
    }, env);

    // 把嵌套的 messages 对象摊平成前端要的字段
    const data = rows.map((r) => {
      const m = Array.isArray(r.messages) ? r.messages[0] : (r.messages || {});
      return {
        id: m.id,
        importance: r.importance,
        group_name: m.group_name,
        sender: m.sender,
        content: m.content,
        summary: r.summary,
        deadline: r.deadline,
        received_at: iso(m.received_at)
      };
    });

    return json(200, Object.assign({}, info, { ok: true, count: data.length, data: data }));
  } catch (err) {
    return json(500, Object.assign({}, info, dbError(err)));
  }
};
