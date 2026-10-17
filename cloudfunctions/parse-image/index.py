"""
parse-image/index.py —— 云函数：POST /api/parse/image

契约见 docs/api-contract.md §2（改版版 · 2026-10-10）。

======================================================================
★ 为什么必须走「两步」（识图 → 提取），不能一步到位
  实测（2026-10-10）：让 glm-4v-flash 边识别边提取任务，
    因它的 max_tokens 硬上限是 1024，内容被截断，**漏掉了「@我 私信」那条真任务**。
    拆成两步后 3 条全对。
  所以这里只让视觉模型做「图片→文字」，提取交给 ai_client.parse_tasks，
  与 /api/parse/text 走【完全相同】的流程 —— 这也满足 PRD 验收 A2：
  「纯图片、纯文字两种输入产出结构完全一致」。

======================================================================
multipart 怎么传进来的？（实测结论，不是猜的）
  CloudBase HTTP 访问服务支持 multipart/form-data：
    - headers['content-type'] 里 boundary 完整保留
    - **整个 multipart 文本被 base64 编码**放进 event.body（isBase64Encoded=True）
  解析逻辑见 multipart.py。

======================================================================
图片大小上限 3 MB（实测决定的）
  网关请求体上限实测在 4~4.5 MB 之间（4 MB 通过、4.5 MB 返回 413），
  而 multipart 全文还要先 base64（膨胀 1.34 倍）才进 event.body，
  所以 3 MB 原图 → base64 约 4.0 MB，刚好不撞上限。
  ★ PRD 第七节原写「10 MB」是错的，实测后已改成 3 MB。
"""

import json
import os
import sys
from datetime import datetime

# ★ 让同目录的模块能被 import 到
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_client      # noqa: E402
import db             # noqa: E402
import multipart      # noqa: E402
import time_parser    # noqa: E402

SERVICE = "ai-schedule"


def _json(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type, X-User-Code",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }


def _base():
    env = os.environ.get("TCB_ENV") or os.environ.get("SCF_NAMESPACE") or "unknown"
    return {"service": SERVICE, "fn": "parse-image", "env": env}


def _user_code(event):
    """取出并清洗个人口令（★ 数据隔离入口，见 tasks/index.py 同名函数的说明）。"""
    headers = event.get("headers") or {}
    raw = None
    for k, v in headers.items():
        if str(k).lower() == "x-user-code":
            raw = v
            break
    if not raw:
        raw = _params(event).get("code")
    return db.normalize_code(raw)


def _iso(dt):
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _format(row):
    """与 /api/parse/text 的 _format 完全一致 —— 契约要求两条路径结构相同。"""
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
    """multipart / AI 错误码 → HTTP 状态码（契约 §0 错误码表）。"""
    return {
        "NO_FILE": 400,
        "EMPTY_INPUT": 400,
        "BAD_BODY": 400,
        "IMAGE_BAD_FORMAT": 415,
        "IMAGE_TOO_LARGE": 413,
        "AI_TIMEOUT": 504,
        "AI_BUSY": 429,
        "NO_API_KEY": 500,
        "AI_BAD_OUTPUT": 500,
    }.get(code, 500)


def main_handler(event, context):
    """CloudBase Python 云函数入口"""
    event = event or {}
    info = _base()
    method = str(event.get("httpMethod", "POST")).upper()

    if method == "OPTIONS":
        return _json(200, {**info, "ok": True})
    if method != "POST":
        return _json(405, {**info, "ok": False,
                           "error": "METHOD_NOT_ALLOWED",
                           "message": "请用 POST 请求"})

    code = _user_code(event)
    if not code:
        return _json(400, {**info, "ok": False,
                           "error": "NO_USER_CODE",
                           "message": "缺少个人口令，请重新打开页面"})

    # ---------- 1. 取图片 ----------
    try:
        f = multipart.parse_file(event)
    except multipart.MultipartError as e:
        return _json(_status_for(e.code), {**info, "ok": False,
                                           "error": e.code,
                                           "message": e.message})

    # ---------- 2. 先落原始内容 ----------
    # ★ image_path 暂存 null —— 图片本身没存到云存储，
    #   我们只保留识别出的文字（raw_text）与大小。原始图片不入库。
    source_id = None
    try:
        source_id = db.insert_source(
            code, "image", raw_text=None,
            image_size=len(f["content"]), status="pending")
    except db.DBError as e:
        print(f"[warn] sources 落库失败：{e.code} {e.message}")

    # ---------- 3. 两步：识图 → 提取 ----------
    try:
        ocr_text = ai_client.ocr(f["content"], f["mime"])
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

    # ★ 识别出的文字要写回 sources.raw_text —— 原始输入必须留痕（PRD）
    try:
        if source_id:
            db.update_raw_text(source_id, ocr_text)
    except db.DBError as e:
        print(f"[warn] raw_text 回写失败：{e.code}")

    try:
        tasks = ai_client.parse_tasks(ocr_text)
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

    # ---------- 4. 落库（与文本路径完全相同的逻辑）----------
    base_time = datetime.now()
    saved = []
    for t in tasks:
        try:
            deadline_at = time_parser.parse_time(t["time_raw"], base_time)
            if deadline_at is None and t["time_raw"]:
                print(f"[info] 时间未能换算，原文保留：{t['time_raw']!r}")
            saved.append(db.insert_task(
                user_code=code,
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

    rows = []
    for tid in saved:
        try:
            row = db.get_task(code, tid)
            if row:
                rows.append(_format(row))
        except db.DBError:
            pass

    # ★ ocr_text 一并返回，方便前端显示「我们识别到了这些文字」，
    #   用户能立刻判断上传的图对不对（契约 §2）。
    return _json(200, {
        **info,
        "ok": True,
        "source_id": source_id,
        "ocr_text": ocr_text,
        "count": len(rows),
        "data": rows,
    })


# CLI 部署 Python 函数时执行方法被填成 index.main，补一个别名兼容
def main(event, context):
    return main_handler(event, context)