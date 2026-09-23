"""群消息智能提醒助手 — 后端入口（Day 7 MVP）

模块分工（依据 TECH_DESIGN 第三节）：
  F1 接收解析  -> app/parser.py + POST /api/messages
  F2 重要性判断 -> app/judge.py（MVP 为规则引擎版，DeepSeek 升级位留好）
  F3 精选推送  -> app/notify.py（MVP 留桩，不接真机）
  F4 待办时间线 -> 本文件 GET / （Jinja2 模板渲染）
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel

from app import db
from app.judge import judge
from app.notify import push_important
from app.parser import parse

app = FastAPI(title="群消息智能提醒助手")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# Day 8：可复用卡片组件 app/static/js/message-card.js 通过 /static 提供给页面
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class IncomingMessage(BaseModel):
    """SmsForwarder 转发内容的接收契约（F1）。"""

    group_name: str | None = None
    sender: str | None = None
    content: str | None = None
    received_at: str | None = None


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/api/health")
def health():
    """骨架自检端点：服务活着就返回 ok。"""
    return {"status": "ok", "app": "群消息智能提醒助手", "day": 7}


@app.post("/api/messages")
def receive_message(msg: IncomingMessage):
    """F1：接住一条转发的通知，解析落库。坏格式不崩溃（F1-3）。"""
    rec = parse(msg.model_dump())
    mid = db.insert_message(rec)

    # F2：解析成功的消息立即过判断，结果写 judgments 表
    result = None
    if rec["parse_status"] == "ok":
        result = judge(rec["sender"] or "", rec["content"] or "")
        db.insert_judgment(mid, result)
        # F3：只推 important（MVP 留桩：BARK_URL 为空，返回 pushed=False）
        if result["importance"] == "important":
            push_important(rec["group_name"], result["summary"] or "")

    return {"id": mid, "parse_status": rec["parse_status"], "judgment": result}


@app.get("/api/messages")
def all_messages():
    """F1 验证辅助：按到达顺序列出全部消息记录。"""
    return db.list_messages()


@app.get("/api/timeline")
def timeline():
    """F4 数据接口：judgments 里 importance=important 的项，供时间线页面用。"""
    return db.list_important()


@app.get("/")
def timeline_page(request: Request):
    """主视图（Day 8）：页面数据为本地 mock，四种状态（加载/正常/空/错误）用
    ?state= 切换；第 3 周再接回 /api/timeline 真实数据。"""
    return templates.TemplateResponse(request, "timeline.html")
