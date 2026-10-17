"""
db.py —— 数据库访问层（改版版· 一期）

======================================================================
★ 读库方式为什么是HTTP API 而不是 pg 直连？
  CloudBase 免费体验版【不开放内网互联】，云函数连内网地址会一直等到
  超时（社区issue 与旧版实测都印证过）。官方推荐走HTTP API（PostgREST）：
    网关：https://<envId>.api.tcloudbasegateway.com/v1/rdb/rest/<table>
    鉴权：Authorization: Bearer <DB_API_KEY>
  这个方式在旧版 Day 17 已经在真库验证通过，可靠。

★ 这个文件不知道「智谱」的存在（那是 ai_client 的事），也不知道 HTTP 细节
  （那是 cloudfunctions/index.js 的事），只管把数据存取成字典。
======================================================================
"""

import os
import json
import urllib.request
import urllib.error
import urllib.parse

# 网关域名：国内地域固定 <envId>.api.tcloudbasegateway.com
ENV_ID = os.environ.get("TCB_ENV") or os.environ.get("SCF_NAMESPACE") or ""
DB_API_KEY = os.environ.get("DB_API_KEY", "")

TIMEOUT = 15


class DBError(Exception):
    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _check():
    if not DB_API_KEY:
        raise DBError(
            "DB_NO_KEY",
            "服务未配置数据库密钥",
            hint="请在云函数环境变量中设置 DB_API_KEY",
        )


def _gateway():
    return f"https://{ENV_ID}.api.tcloudbasegateway.com/v1/rdb/rest"


def _request(method, table, params=None, body=None):
    """统一的 HTTP 封装。返回解析后的 JSON。"""
    _check()
    url = f"{_gateway()}/{table}"
    if params:
        qs = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
        if qs:
            url += "?" + qs
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {DB_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise DBError("DB_HTTP", f"数据库请求失败（{e.code}）", detail)
    except Exception as e:
        raise DBError("DB_NETWORK", "数据库连接失败", str(e))


# ======================================================================
# 查询
# ======================================================================
def select(table, **params):
    """查多行。例：select('tasks', select='id,title', order='id.desc', limit='10')"""
    return _request("GET", table, params=params) or []


def insert(table, **fields):
    """插入一行，返回新行 id。

    ★ 注意：PostgREST 需要用 Prefer: return=representation 才会回传数据，
      但我们只要 id，所以先查 max(id) 再插入 —— 简单可靠，
      单用户自用场景下并发极低，竞态风险可忽略。
    """
    rows = select(table, select="id", order="id.desc", limit="1")
    next_id = (rows[0]["id"] + 1) if rows else 1
    fields["id"] = next_id
    _request("POST", table, body=fields)
    return next_id


def update(table, row_id, **fields):
    """按 id 更新一行，返回受影响行数。"""
    res = _request(
        "PATCH",
        table,
        params={"id": f"eq.{row_id}"},
        body=fields,
    )
    return len(res) if isinstance(res, list) else 0


def delete(table, row_id):
    """按 id 删除，返回受影响行数。"""
    res = _request("DELETE", table, params={"id": f"eq.{row_id}"})
    return len(res) if isinstance(res, list) else 0


# ======================================================================
# 业务动作
# ======================================================================
def insert_source(input_type, raw_text=None, image_size=None, status="pending"):
    """记一条用户上传的原始内容。"""
    return insert(
        "sources",
        input_type=input_type,
        raw_text=raw_text,
        image_size=image_size,
        parse_status=status,
    )


def mark_source_parsed(source_id, status, error_message=None):
    """更新上传记录的解析状态。失败也要留痕（PRD 要求）。"""
    update(
        "sources",
        source_id,
        parse_status=status,
        error_message=error_message,
    )


def update_raw_text(source_id, raw_text):
    """把识别/解析出的文字写回 sources.raw_text。

    图片输入时：先插入一条只有 image_size 的记录（raw_text 还不知道），
    识图完成后再回填文字 —— 原始输入必须留痕，AI 抽错了要能拿原文重跑。
    """
    return update("sources", source_id, raw_text=raw_text)


def insert_task(source_id, title, detail=None, deadline_at=None, deadline_raw=None,
                parsed_by=None):
    """插入一条任务。"""
    return insert(
        "tasks",
        source_id=source_id,
        title=title,
        detail=detail or "",
        # 无时间时存NULL —— 数据库约束要求 null 就必须是真 null
        deadline_at=deadline_at,
        deadline_raw=deadline_raw,
        status="pending",
        parsed_by=parsed_by or "ai",
    )


def list_tasks(status=None, limit=50):
    """任务列表。status 为 None 时返回全部。"""
    params = {
        "select": "id,title,deadline_at,deadline_raw,detail,status,created_at,completed_at",
        "order": "deadline_at.asc.nullslast,created_at.desc",
        "limit": str(limit),
    }
    if status:
        params["status"] = f"eq.{status}"
    return select("tasks", **params)


def get_task(task_id):
    """按 id 取单条，找不到返回 None。"""
    rows = select(
        "tasks",
        select="id,title,deadline_at,deadline_raw,detail,status,created_at,completed_at",
        id=f"eq.{task_id}",
        limit="1",
    )
    return rows[0] if rows else None


def today_todo():
    """当日待办总表——直接走数据库视图，不在代码里拼时间条件。

    视图定义见 db/schema.sql：有截止时间的按时间排，没时间的沉底。
    """
    return select(
        "v_today_todo",
        select="id,title,deadline_at,deadline_raw,detail,status,created_at,completed_at",
        order="deadline_at.asc.nullslast,created_at.desc",
    )