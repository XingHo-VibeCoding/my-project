"""F1 消息解析层

输入：SmsForwarder POST 来的转发内容（JSON）。
约定格式（MVP 契约）：
  {"group_name": "打卡群", "sender": "班长", "content": "@所有人 本周五 22:00 前交作业", "received_at": "2026-09-22 21:00:00"}
  received_at 可省略，默认取服务器当前时间。
职责：字段完整性校验 —— 缺关键字段不抛异常（F1-3 不崩溃），返回 parse_status='failed' 的记录。
"""
from datetime import datetime


def parse(payload: dict) -> dict:
    """把转发来的 JSON 转成待入库的消息记录。绝不抛异常。"""
    group_name = (payload.get("group_name") or "").strip()
    sender = (payload.get("sender") or "").strip()
    content = (payload.get("content") or "").strip()
    received_at = (payload.get("received_at") or "").strip() or datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")

    if not sender or not content:  # 群名允许缺（私聊/系统通知场景），发送人和内容不能缺
        status = "failed"
    else:
        status = "ok"

    return {
        "group_name": group_name or None,
        "sender": sender or None,
        "content": content or None,
        "received_at": received_at,
        "parse_status": status,
    }
