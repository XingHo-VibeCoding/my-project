"""
time_parser.py —— 中文时间表述 → 绝对时间（改版版 · 一期）

======================================================================
解决什么问题？
  AI 提取出来的任务，时间是**原文表述**（deadline_raw）：
      「本周五 22:00 前」「周五下午 3 点」「下周一 14:00」「今晚 21:00」
  但数据库的 deadline_at 要的是**绝对时间**（TIMESTAMPTZ），
  否则 v_today_todo 视图没法按时间排序、没法判断「今天要做什么」。
  这个模块负责两者之间的换算。

======================================================================
三个产品决策（2026-10-10 学习者拍板，写在这里改代码前先看）
--------------------------------------------------------------------
①「本周五」这类已经过去的时间 → 解析成**下一个**周五
   理由：截止时间的意义是「没做就赶紧做」，用户周五晚上记「本周五交作业」，
        想要的是「下一个能交的机会」，不是让他看一个红色过期。
   例：今天 10-17（周六）说「本周五22:00」→ 10-23（周五）22:00

② 只写日期不写时间（「周五开会」）→ 当天 **23:59**
   理由：表示「这天内要完成」，23:59 是当天最后一个时刻。
        比存 00:00 更符合直觉（00:00 会让排序跑到最前面，误导用户）。

③ **不做 AI 兜底**：规则解析不了就存 NULL，原文留在 deadline_raw。
   理由：★ 绝对时间算错比算不出来更糟 ★
        模型可能把「下周一」算成错误日期（本周一 vs 下周一差 7 天），
        用户看到错误日期会被误导，比「显示原文让用户自己定」危险得多。
        宁可少算，不可算错。
======================================================================
"""

import re
from datetime import datetime, date, timedelta, time as dtime

# 一天中的默认时间（决策②）
DEFAULT_HOUR = 23
DEFAULT_MINUTE = 59

# 区分「没有时刻」和「时刻非法」两种情况——
# 这个区分很重要：把非法的 25:00 当成「没写时间」会静默编一个 23:59 出来，
# 那就是在骗用户。宁可整条解析失败，让用户自己填。
INVALID_CLOCK = object()

WEEKDAY_MAP = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
    "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6,
}

# ---------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------
def _extract_clock(text):
    """抽出「22:00」「3点」「下午3点半」这类时刻。

    返回 (hour, minute) 或 None。
    ★ 注意顺序：先匹配「下午/晚上/上午/中午」这类前缀，
      否则「下午3点」里的 3 会被当成 3:00，方向就错了。
    """
    # 半角/全角冒号都算
    t = text.replace("：", ":")

    # 下午/晚上 → +12（注意 12点 下午 = 12点，不能 +12）
    pm = re.search(r"(下午|晚上|傍晚|夜里)", t)
    am = re.search(r"(上午|早上|早晨|凌晨|中午)", t)

    m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if pm and 1 <= h <= 11:
            h += 12
        if h == 24:
            h = 0
        return _valid_clock(h, mi)

    m = re.search(r"(\d{1,2})\s*[点时]\s*(半|(\d{1,2})\s*分)?", t)
    if m:
        h = int(m.group(1))
        mi = 0
        if m.group(2) == "半":
            mi = 30
        elif m.group(3):
            mi = int(m.group(3))
        if pm and 1 <= h <= 11:
            h += 12
        if am and h == 12:
            h = 0
        if h == 24:
            h = 0
        return _valid_clock(h, mi)

    # 「中午12点」这类
    if "中午" in t and not re.search(r"\d", t):
        return 12, 0
    return None


def _valid_clock(h, mi):
    """小时必须在 0-23，分钟 0-59。

    返回 (h, mi) 表示合法；
    返回 None 表示这段话里本来就没写时刻（正常，用默认时刻）；
    ★ 返回 INVALID_CLOCK 表示写了但写错了（如 25:00）——
      调用方必须据此让整条解析失败，不能静默换成别的时间。
    """
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return INVALID_CLOCK


def _next_weekday(base, target_wd, forward_only=True):
    """算 base 之后的下一个星期几。

    ★ 决策①：forward_only=True 时，今天之后的下一个 target（今天就是该周几也算）
      —— 这样「周五晚上记『本周五22点』」拿到的是下周五而不是今天的。
      实际上：如果 base 就是周五，且已经过了目标时刻，也应该指向下周五。
    """
    delta = (target_wd - base.weekday()) % 7
    return base + timedelta(days=delta)


def _week_of(base, target_wd):
    """算「本周X」的确切日期。

    定义：本周 = 周一至周日。本周一 = base 所在周的周一。
    ★ 决策①：若算出来的日子已经过去了（含时刻已过），顺延一周。
    """
    monday = base - timedelta(days=base.weekday())
    target = monday + timedelta(days=target_wd)
    if target < base:
        target += timedelta(days=7)
    return target


# ---------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------
def parse_time(raw, base=None):
    """把中文时间表述换算成 datetime。

    参数：
      raw   —— AI 提取出的原文表述，如「本周五 22:00 前」「下周一 14:00」
      base  —— 基准日期（默认今天）。真实使用时应传入「录入当天」，
               因为「明天」是相对录入时刻说的。

    返回：
      datetime —— 换算成功
      None     —— 解析不了（调用方应保留 deadline_raw，deadline_at 存 NULL）
    """
    if not raw:
        return None
    if isinstance(raw, str) and raw.strip().lower() in (
            "null", "none", "n/a", "无", "没有", "未指定"):
        return None

    base_dt = base or datetime.now()
    if isinstance(base_dt, date) and not isinstance(base_dt, datetime):
        base_dt = datetime.combine(base_dt, dtime(0, 0))
    base_date = base_dt.date()

    text = str(raw).strip()
    # 归一化：去掉「前」「之前」等动作词（不影响时间本身）
    text = re.sub(r"(截止|截至|之前|以前|以前|前|内|之内)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    clock = _extract_clock(text)

    # ★ 实测抓到的问题：「周五25:00」这种非法时刻，_extract_clock 返回 None，
    #   之前会静默落到默认的 23:59 —— 相当于编了一个时间出来。
    #   区分两种 None：
    #     None      = 这段话里本来就没有时刻（正常，用默认时刻）
    #     非法标志   = 有时刻但写错了（如25:00）→ 整个解析判失败（决策③，宁可不算）
    if clock is INVALID_CLOCK:
        return None

    # ===== 1. 绝对日期：2026-10-15 18:00 / 10月15日 18点 / 10/15 =====
    m = re.search(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*[日号]?", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            hh, mm = clock if clock else (DEFAULT_HOUR, DEFAULT_MINUTE)
            return datetime(y, mo, d, hh, mm)
        except ValueError:
            return None

    m = re.search(r"(?<!\d)(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*[日号]?(?!\d)", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = base_date.year
        try:
            # 没有年份信息：若算出来比今天早太多，认为是明年
            hh, mm = clock if clock else (DEFAULT_HOUR, DEFAULT_MINUTE)
            cand = datetime(y, mo, d, hh, mm)
            if cand < base_dt - timedelta(days=180):
                cand = datetime(y + 1, mo, d, hh, mm)
            return cand
        except ValueError:
            return None

    # ===== 2. 今天/明天/后天/大后天 =====
    # ★ 长词必须放前面：「大后天」要先于「后天」匹配，否则会匹配成「后天」。
    # ★ 「明早/明上午/明中午/明晚/明天」都覆盖 —— 实测漏过「明早」。
    day_words = [
        ("大后天", 3), ("后天", 2), ("明天", 1),
        ("今日", 0), ("今天", 0), ("今晚", 0),
        ("今早", 0), ("今上午", 0), ("今中午", 0),
        ("明早", 1), ("明上午", 1), ("明中午", 1), ("明晚", 1), ("明晚间", 1),
    ]
    for word, offset in day_words:
        if word in text:
            target = base_date + timedelta(days=offset)
            hh, mm = clock if clock else (DEFAULT_HOUR, DEFAULT_MINUTE)
            # 没写时刻时，按「早晚」给个合理的默认，而不是 23:59
            # 「明早」没说几点 → 早上 8 点比23:59 更符合直觉
            if clock is None:
                if "早" in word or "上午" in word:
                    hh, mm = 8, 0
                elif "晚" in word:
                    hh, mm = 21, 0
                elif "中午" in word:
                    hh, mm = 12, 0
                else:
                    hh, mm = DEFAULT_HOUR, DEFAULT_MINUTE
            return datetime.combine(target, dtime(hh, mm))

    # ===== 3. 周几类 =====
    # 3a. 下周X / 下星期X —— 明确指下一个自然周的周几
    m = re.search(r"下\s*(?:周|星期)\s*([一二三四五六日天1-7])", text)
    if m:
        wd = WEEKDAY_MAP[m.group(1)]
        # 下周 = 本周一 +7，再加到目标周几
        monday = base_date - timedelta(days=base_date.weekday())
        target = monday + timedelta(days=7 + wd)
        hh, mm = clock if clock else (DEFAULT_HOUR, DEFAULT_MINUTE)
        return datetime.combine(target, dtime(hh, mm))

    # 3b. 本周X / 这周X / 星期X
    is_this_week = False
    m = re.search(r"(?:本|这|这个)\s*(?:周|星期)\s*([一二三四五六日天1-7])", text)
    if m:
        is_this_week = True
        wd = WEEKDAY_MAP[m.group(1)]
    else:
        m = re.search(r"(?:周|星期)\s*([一二三四五六日天1-7])", text)
        if m:
            is_this_week = True
            wd = WEEKDAY_MAP[m.group(1)]

    if is_this_week:
        target_date = _week_of(base_date, wd)
        hh, mm = clock if clock else (DEFAULT_HOUR, DEFAULT_MINUTE)
        cand = datetime.combine(target_date, dtime(hh, mm))
        # ★ 决策①：如果这个时刻已经过去，顺延一周
        if cand < base_dt:
            cand += timedelta(days=7)
        return cand

    # ===== 4. 其余情况 =====
    # 「明晚/明早/今晚」等已在第 2 节的 day_words 里统一处理，
    # 走到这里说明没匹配到任何已知表述 → 解析不了，不猜（决策③）
    return None


def describe(raw, dt):
    """给用户看的说明：换算成了什么 / 为什么是空的。

    前端展示用——用户看到「下周三」被存成 NULL 时，
    要告诉他原文还在，让他自己判断，而不是显示一个空白。
    """
    if dt is None:
        if not raw:
            return "未指定时间"
        return f"原文「{raw}」未识别出具体日期，可手动补充"
    if not raw:
        return "未指定时间"
    return f"{raw} → {dt.strftime('%Y-%m-%d %H:%M')}"