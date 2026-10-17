"""
tasks/index.py —— 云函数：任务管理（契约 §3）

======================================================================
一个函数处理四个操作，靠 httpMethod 分流（契约 §3）：
    GET    /api/tasks       → 任务列表（?status=pending|done&limit=N）
    GET    /api/today       → 当日待办总表
    PATCH  /api/tasks?id=1   → 改任务 / 打卡 / 取消打卡
    DELETE /api/tasks?id=1   → 删除任务

★ 为什么 id 走 query 而不是路径（/api/tasks/1）？
  CloudBase HTTP 访问服务**不能把路径参数传进来**（旧版 Day 17 实测：
  event.path 恒为"/"），所以只能用 ?id=1。这是平台限制，不是设计选择。

★ 为什么一个函数管这么多操作？
  契约里它们共用同一批数据、同一套返回结构，放一起省事。
  path 路由虽然不可用，但 httpMethod 是可靠的。

★ 打卡为什么要同时管 status 和 completed_at？
  数据库有约束 tasks_completed_consistency 强制两者一致：
  done 必须有时间戳、pending 必须为 NULL。
  所以打卡/取消打卡这两个动作必须由服务端同时改两个字段，
  前端只传 status 就够 —— 不能让前端自己填时间（会填错）。
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db             # noqa: E402

SERVICE = "ai-schedule"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _json(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET, PATCH, DELETE, OPTIONS",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }


def _base():
    env = os.environ.get("TCB_ENV") or os.environ.get("SCF_NAMESPACE") or "unknown"
    return {"service": SERVICE, "fn": "tasks", "env": env}


def _iso(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _format(row):
    """契约 §3 的任务项字段。"""
    if not row:
        return None
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "deadline_at": _iso(row.get("deadline_at")),
        "deadline_raw": row.get("deadline_raw"),
        "detail": row.get("detail"),
        "status": row.get("status"),
        "created_at": _iso(row.get("created_at")),
        "completed_at": _iso(row.get("completed_at")),
    }


def _read_limit(params):
    try:
        n = int(params.get("limit", DEFAULT_LIMIT))
        if n <= 0:
            return DEFAULT_LIMIT
        return min(n, MAX_LIMIT)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def _parse_body(event):
    body = event.get("body")
    if not body:
        return {}
    if event.get("isBase64Encoded"):
        import base64
        try:
            body = base64.b64decode(body).decode("utf-8", errors="replace")
        except Exception:
            return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {}


def _to_id(raw):
    """把外部传来的 id 归一化成 int 或 None。

    ★ 实测踩到的坑（2026-10-17）：
      查询串里的 id 永远是【字符串】 "1"，而数据库返回的 id 是【整数】 1。
      后面拿字符串 id 去比对/查字典会全部失配 —— 表现为「任务明明存在却报 404」。
      所以这里统一转 int，转不了就返回 None 交给上层报 400。
    """
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _params(event):
    """查询串参数。HTTP 访问服务通常已解析好，但个别情况需自己解。"""
    q = event.get("queryStringParameters") or {}
    if not q and event.get("queryString"):
        from urllib.parse import parse_qs
        q = {k: v[0] for k, v in parse_qs(event["queryString"]).items()}
    return q


def main_handler(event, context):
    event = event or {}
    info = _base()
    method = str(event.get("httpMethod", "GET")).upper()
    params = _params(event)

    # ---------- 今日待办：走数据库视图，不在代码里拼时间条件 ----------
    if method == "GET" and _is_today(event, params):
        try:
            rows = db.today_todo()
            data = [_format(r) for r in rows if r]
            return _json(200, {**info, "ok": True, "count": len(data), "data": data})
        except db.DBError as e:
            return _db_error(e)

    # ---------- DELETE ----------
    if method == "DELETE":
        tid = _to_id(params.get("id") or _parse_body(event).get("id"))
        if tid is None:
            return _json(400, {**info, "ok": False, "error": "EMPTY_INPUT",
                               "message": "缺少任务 id"})
        try:
            if not db.get_task(tid):
                return _json(404, {**info, "ok": False, "error": "NOT_FOUND",
                                   "message": "任务不存在或已删除"})
            db.delete("tasks", tid)
            return _json(200, {**info, "ok": True, "deleted_id": tid})
        except (db.DBError, ValueError) as e:
            return _db_error(e) if isinstance(e, db.DBError) else _json(
                400, {**info, "ok": False, "error": "EMPTY_INPUT",
                      "message": "任务 id 不合法"})

    # ---------- PATCH：改任务 / 打卡 ----------
    if method == "PATCH":
        body = _parse_body(event)
        tid = _to_id(params.get("id") or body.get("id"))
        if tid is None:
            return _json(400, {**info, "ok": False, "error": "EMPTY_INPUT",
                               "message": "缺少任务 id"})
        fields = {}
        if "title" in body and body["title"]:
            title = str(body["title"]).strip()
            if not title:
                return _json(400, {**info, "ok": False, "error": "EMPTY_INPUT",
                                   "message": "任务标题不能为空"})
            fields["title"] = title
        if "detail" in body:
            fields["detail"] = str(body["detail"] or "")
        if "deadline_at" in body:
            # 允许置null（表示清空时间），也要能改
            fields["deadline_at"] = body["deadline_at"] or None

        # ★ 打卡：status 与 completed_at 必须同时改，否则违反数据库约束
        if "status" in body:
            st = str(body["status"])
            if st not in ("pending", "done"):
                return _json(400, {**info, "ok": False, "error": "EMPTY_INPUT",
                                   "message": "状态只能是 pending 或 done"})
            fields["status"] = st
            fields["completed_at"] = datetime.now().isoformat() if st == "done" else None

        if not fields:
            return _json(400, {**info, "ok": False, "error": "EMPTY_INPUT",
                               "message": "没有要修改的内容"})

        try:
            if not db.get_task(tid):
                return _json(404, {**info, "ok": False, "error": "NOT_FOUND",
                                   "message": "任务不存在或已删除"})
            db.update("tasks", tid, **fields)
            return _json(200, {**info, "ok": True, "data": _format(db.get_task(tid))})
        except (db.DBError, ValueError):
            return _json(400, {**info, "ok": False, "error": "EMPTY_INPUT",
                               "message": "参数不合法"})

    # ---------- GET：任务列表 ----------
    if method == "GET":
        try:
            rows = db.list_tasks(status=params.get("status"),
                                 limit=_read_limit(params))
            data = [_format(r) for r in rows if r]
            return _json(200, {**info, "ok": True, "count": len(data), "data": data})
        except db.DBError as e:
            return _db_error(e)

    if method == "OPTIONS":
        return _json(200, {**info, "ok": True})

    return _json(405, {**info, "ok": False, "error": "METHOD_NOT_ALLOWED",
                       "message": "不支持的请求方法"})


def _is_today(event, params):
    """判断是不是 /api/today 这个路径。

    ★ 已知 event.path 恒为 "/"（旧版实测），所以不能靠 path 判断。
    这里靠两种方式：
      1) 显式传 ?view=today
      2) event 里有 path 且以 /today 结尾（万一平台哪天支持了）
    ★ 前端一律用 ?view=today，这个是最可靠的。
    """
    if params.get("view") == "today":
        return True
    p = str(event.get("path") or "")
    return p.endswith("/today")


def _db_error(e):
    code = "DB_UNAVAILABLE"
    msg = "数据库暂时不可用"
    if getattr(e, "code", "") == "DB_NO_KEY":
        code, msg = "DB_UNAVAILABLE", "服务未配置数据库密钥"
    return _json(500, {**info_of(e), "ok": False, "error": code,
                       "message": msg, "hint": getattr(e, "hint", None)})


def info_of(e):
    env = os.environ.get("TCB_ENV") or os.environ.get("SCF_NAMESPACE") or "unknown"
    return {"service": SERVICE, "fn": "tasks", "env": env}


def main(event, context):
    return main_handler(event, context)