"""
parse-text/index.py —— 云函数：POST /api/parse/text

契约见 docs/api-contract.md §1（改版版 · 2026-10-10）。

======================================================================
目录结构（CloudBase Python 云函数硬要求）
  parse-text/
    ├── index.py        ← 入口文件，必须叫这个名字
    ├── ai_client.py    ← 依赖必须与 index.py 同级！
    └── db.py
  ★ 为什么必须同级：官方明确「依赖放在子目录/全局路径，云函数找不到」。
    不能递归搜索子目录，所以 import 不到上一层的文件。
    这也是为什么 ai_client.py / db.py 在仓库根目录有一份（本地开发用），
    部署时复制一份到函数目录里—— 复制，不是软链。
======================================================================

★ 为什么这个函数只做「文本」这一件事？
  CloudBase「HTTP 访问服务」转给事件函数时 event.path恒为 "/"，
  没法靠 path 路由（旧版 Day 17 实测踩过），所以一个函数只干一件事。

★ 为什么超时必须调高？
  AI 提取 3~10 秒 + Python 冷启动几秒。控制台默认超时只有 3 秒，
  必须改成 60秒以上，见 cloudbaserc.json 里的 timeout 配置。
"""

import json
import os
import sys
from datetime import datetime

# ★ 让同目录的 ai_client / db / time_parser 能被 import 到
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_client      # noqa: E402
import db             # noqa: E402
import time_parser    # noqa: E402

SERVICE = "ai-schedule"
MAX_TEXT_LEN = 20000


def _json(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            # CORS：静态托管站与云函数不同域，前端必须能跨域调
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }


def _base():
    env = os.environ.get("TCB_ENV") or os.environ.get("SCF_NAMESPACE") or "unknown"
    return {"service": SERVICE, "fn": "parse-text", "env": env}


def _parse_body(event):
    """从 event 取请求体。

    HTTP 访问服务转过来的 body 是 base64 编码的（isBase64Encoded 标记），
    这一层必须自己解—— 旧版就是因为没解，body 一直是空的。
    """
    body = event.get("body")
    if not body:
        return None
    if event.get("isBase64Encoded"):
        import base64
        try:
            body = base64.b64decode(body).decode("utf-8", errors="replace")
        except Exception:
            return None
    if isinstance(body, (dict, list)):
        return body
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None


def main_handler(event, context):
    """CloudBase Python 云函数入口：执行方法 index.main_handler"""
    event = event or {}
    info = _base()
    method = str(event.get("httpMethod", "POST")).upper()

    if method == "OPTIONS":
        return _json(200, {**info, "ok": True})
    if method != "POST":
        return _json(405, {**info, "ok": False,
                           "error": "METHOD_NOT_ALLOWED",
                           "message": "请用 POST 请求"})

    payload = _parse_body(event)
    if not payload:
        return _json(400, {**info, "ok": False,
                           "error": "EMPTY_INPUT",
                           "message": "请求体为空，请重新提交"})

    raw_text = str(payload.get("raw_text") or "").strip()

    # ---------- 入参校验（契约 §1）----------
    if not raw_text:
        return _json(400, {**info, "ok": False,
                           "error": "EMPTY_INPUT",
                           "message": "请先粘贴一些文字"})
    if len(raw_text) > MAX_TEXT_LEN:
        return _json(400, {**info, "ok": False,
                           "error": "EMPTY_INPUT",
                           "message": f"文字太长了（{len(raw_text)} 字），"
                                      f"请控制在 {MAX_TEXT_LEN} 字以内"})

    # ---------- 1. 先落原始内容（可追溯，PRD 要求原始输入不丢）----------
    source_id = None
    try:
        source_id = db.insert_source("text", raw_text=raw_text, status="pending")
    except db.DBError as e:
        # 数据库挂了不应该让整个功能瘫掉：照常解析，只是这批不落库
        print(f"[warn] sources 落库失败：{e.code} {e.message}")

    # ---------- 2. AI 提取 ----------
    try:
        tasks = ai_client.parse_tasks(raw_text)
    except ai_client.AIError as e:
        if source_id:
            try:
                db.mark_source_parsed(source_id, "failed", str(e.message)[:200])
            except db.DBError:
                pass
        return _json(_status_for(e.code), {**info, "ok": False,
                                           "error": e.code,
                                           "message": e.message,
                                           "hint": e.hint})

    # ---------- 3. 落库 ----------
    # ★ 时间换算在【落库前】做完，理由有二（TECH_DESIGN_V2 §3.3）：
    #   1) v_today_todo 视图是按 deadline_at 排序的，不落库就没法按时间排
    #   2) 换算要以「录入当天」为基准，放在服务端算才准确
    #     （浏览器时区不可靠，且用户可能在不同时区改同一条记录）
    #解析不了就存 NULL，deadline_raw 保留原文 —— 宁可少算不可算错（决策③）
    base_time = datetime.now()
    saved = []
    for t in tasks:
        try:
            deadline_at = time_parser.parse_time(t["time_raw"], base_time)
            if deadline_at is None and t["time_raw"]:
                print(f"[info] 时间未能换算，原文保留：{t['time_raw']!r}")
            saved.append(db.insert_task(
                source_id=source_id,
                title=t["title"],
                detail=t["detail"],
                deadline_at=_iso(deadline_at),
                deadline_raw=t["time_raw"],
                parsed_by=ai_client.CONFIG["text_model"],
            ))
        except db.DBError as e:
            print(f"[warn] task 落库失败：{e.code} {e.message}")

    if source_id:
        try:
            db.mark_source_parsed(source_id, "ok")
        except db.DBError:
            pass

    # ---------- 4. 按契约返回 ----------
    rows = []
    for tid in saved:
        try:
            row = db.get_task(tid)
            if row:
                rows.append(_format(row))
        except db.DBError:
            pass

    return _json(200, {
        **info,
        "ok": True,
        "source_id": source_id,
        "ocr_text": None,          # 文本输入恒为 null（契约 §1）
        "count": len(rows),
        "data": rows,
    })


def _iso(dt):
    """datetime → ISO 8601 字符串；None / 已是字符串的值原样返回。

    从数据库读回来的值可能是 datetime，也可能是 HTTP API 序列化后的字符串
    （字符串没有 .isoformat，直接调会 AttributeError）。
    """
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _format(row):
    """按契约 §1 的字段形状输出。

    读回来的值可能是 datetime 也可能是字符串（取决于 HTTP API 的 JSON 序列化），
    所以统一过一道 _iso。
    """
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "deadline_at": _iso(row.get("deadline_at")),
        "deadline_raw": row.get("deadline_raw"),
        "detail": row.get("detail"),
        "status": row.get("status"),
        "created_at": _iso(row.get("created_at")),
    }


def _status_for(code):
    """AI 错误码 → HTTP 状态码（与契约 §0 错误码表严格一致）。"""
    return {
        "EMPTY_INPUT": 400,
        "AI_TIMEOUT": 504,
        "AI_BUSY": 429,
        "NO_API_KEY": 500,
        "AI_BAD_OUTPUT": 500,
    }.get(code, 500)

# ======================================================================
# 兼容入口：CLI 部署 Python 函数时会把「执行方法」填成 index.main，
# 而官方Python 规范要写 index.main_handler。实测踩过：
#   Execution method = index.main  →  调用报 "handler not found"
# 补一个 main 别名，两种配置都能跑起来，避免下次再踩。
# ======================================================================
def main(event, context):
    return main_handler(event, context)
