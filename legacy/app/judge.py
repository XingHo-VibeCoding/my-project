"""F2 重要性判断 — 规则引擎版（Day 7 MVP）

今天你拍板：先用规则引擎跑通，不联网、不注册。
DeepSeek 升级位：judge_deepseek() 的函数签名已留好（见文件末尾），
注册拿到 API key 那天，把 main.py 里的调用切过去即可，其余代码不动。

判断信号（打分制，>=2 分判 important）：
  +3  @所有人 / @我        —— 点名，几乎必是任务或紧急通知
  +3  截止时间              —— 「X前」「X点前」「X之前」等带时间要求的行动
  +3  规则/安排变更         —— 「改到」「变更」「从下周起」「别记错」
  +2  行动要求词            —— 「交」「提交」「交作业」「记得」「报名」「截止」
  纯表情 / 过短闲聊         —— 直接判 chat（闲聊）
"""
import re
from datetime import datetime, timedelta

AT_PATTERN = re.compile(r"@所有人|@我\b")
DEADLINE_PATTERN = re.compile(
    r"(\d{1,2}\s*月\s*\d{1,2}\s*[日号]|\d{1,2}\s*[:：]\s*\d{2}|周[一二三四五六日天]"
    r"|今晚|明晚|本周|下周|本周末|月底|今天|明天|后天)(?:\s*\d{1,2}\s*[:：]\s*\d{2})?"
)
DEADLINE_ACTION_PATTERN = re.compile(r"(?:前|之前|以前|截止|截至)")
CHANGE_PATTERN = re.compile(r"改到|变更|调整|从下周起|从下周|别记错|注意：")
ACTION_PATTERN = re.compile(r"交作业|提交|上交|报名|回复|回复我|记得|别忘|截止")
EMOJI_ONLY_PATTERN = re.compile(r"^[\s\[\（(【{:：*☆,.。!！?？~～\-—_0-9a-zA-Z表情\s]*$")


def _is_chat(content: str) -> bool:
    """纯表情、'打球+1' 式的极短附和，都算闲聊。"""
    if EMOJI_ONLY_PATTERN.match(content):
        return True
    return len(content) <= 4 and not AT_PATTERN.search(content)


def _extract_deadline(content: str) -> str | None:
    """提取截止时间短语（规则版不换算成绝对时间，原样返回给 F4 展示）。"""
    for m in DEADLINE_PATTERN.finditer(content):
        tail = content[m.end():m.end() + 6]
        if DEADLINE_ACTION_PATTERN.search(tail) or DEADLINE_ACTION_PATTERN.search(
                content[max(0, m.start() - 4):m.start()]):
            return m.group(0)
    return None


def _summary(sender: str, content: str) -> str:
    """一句话要点：去 @ 前缀，截前 30 字。"""
    text = re.sub(r"^@所有人\s*|^@我\s*", "", content).strip()
    return f"{sender}：{text[:30]}"


def judge(sender: str, content: str) -> dict:
    """一条消息 -> {importance, summary, deadline}。永不抛异常。"""
    try:
        if _is_chat(content):
            return {"importance": "chat", "summary": None, "deadline": None}

        score = 0
        if AT_PATTERN.search(content):
            score += 3
        deadline = _extract_deadline(content)
        if deadline:
            score += 3
        if CHANGE_PATTERN.search(content):
            score += 3
        if ACTION_PATTERN.search(content):
            score += 2

        if score >= 2:
            importance = "important"
        elif score >= 1:
            importance = "normal"
        else:
            importance = "chat"

        return {
            "importance": importance,
            "summary": _summary(sender, content) if importance != "chat" else None,
            "deadline": deadline,
        }
    except Exception:
        return {"importance": "normal", "summary": None, "deadline": None}


def judge_deepseek(sender: str, content: str) -> dict:
    """DeepSeek 升级位（今天不用）。注册拿到 key 后实现此函数，
    main.py 里把 judge 换成 judge_deepseek 即可，上下游不动。"""
    raise NotImplementedError("Day 7 规则引擎版：未接 DeepSeek")
