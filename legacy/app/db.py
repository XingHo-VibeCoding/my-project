"""SQLite 数据层（依据 TECH_DESIGN 3.2 落库设计）

表 messages：F1 的接收记录
  id / group_name / sender / content / received_at / parse_status(ok|failed)
表 judgments：F2 的判断结果（②-3 才使用，此处一并建好表结构）
  id / message_id / importance(important|normal|chat) / summary / deadline / judged_at
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name   TEXT,
    sender       TEXT,
    content      TEXT,
    received_at  TEXT,
    parse_status TEXT NOT NULL DEFAULT 'ok'
);
CREATE TABLE IF NOT EXISTS judgments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    importance TEXT NOT NULL,
    summary    TEXT,
    deadline   TEXT,
    judged_at  TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_message(rec: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (group_name, sender, content, received_at, parse_status)"
            " VALUES (:group_name, :sender, :content, :received_at, :parse_status)",
            rec,
        )
        return cur.lastrowid


def list_messages() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM messages ORDER BY id ASC")]


def insert_judgment(message_id: int, result: dict) -> int:
    """F2 判断结果落库（TECH_DESIGN：chat 项不落 judgments，出口即丢弃）。"""
    if result["importance"] == "chat":
        return 0
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO judgments (message_id, importance, summary, deadline, judged_at)"
            " VALUES (:message_id, :importance, :summary, :deadline, :judged_at)",
            {
                "message_id": message_id,
                "importance": result["importance"],
                "summary": result["summary"],
                "deadline": result["deadline"],
                "judged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        return cur.lastrowid


def list_important() -> list[dict]:
    """F4：取全部 important 项（含消息原文信息），按 id 升序。"""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT j.id, j.importance, j.summary, j.deadline, j.judged_at,"
            "       m.group_name, m.sender, m.content, m.received_at"
            "  FROM judgments j JOIN messages m ON j.message_id = m.id"
            " WHERE j.importance = 'important' ORDER BY j.id ASC")]
