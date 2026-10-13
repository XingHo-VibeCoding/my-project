"""
ai_client.py —— AI 调用层（改版版 · 一期）

======================================================================
★ 这个文件是整个项目里【唯一】知道「智谱 GLM」这个名字的地方。
  PRD 五、3 要求「后端统一封装 AI 调用层，方便后续随时切换模型」。

  验收标准（写进文档了，要能验）：
    ★ ai_client.py 之外的文件，出现 bigmodel / zhipu 字样的文件数 = 0
  将来换模型（免费 → 付费，或换厂商），只改本文件顶部的 CONFIG。
======================================================================

本文件吸收的 5 个实测坑（都是踩过的，不写下来会再踩）：

1. 默认开思考模式 → message.content 是【空字符串】，内容在 reasoning_content 里
   → 本文件强制传 "thinking":{"type":"disabled"}

2. 免费模型并发只有 1 → 连发两次就HTTP 429
   → 所有调用【自动重试 + 指数退避】，调用方无需关心

3. glm-4v-flash 的 max_tokens 上限是 1024 → 传 2000 直接 HTTP 400 code=1210
   → 本文件按模型自动选合法的 max_tokens

4. 返回常带 markdown 代码块 ```json 包裹 → json.loads 直接崩
   → parse_json() 自动清洗。★ 注意：行为不稳定（有时不包裹），所以清洗不能省

5. 识图【必须走两步】：glm-4v-flash 边识别边提取会因 1024 token 上限被截断，
   实测漏掉「@我」这条真任务
   → vision() 只负责转文字，提取交给 parse_tasks()，与文字路径汇合
"""

import json
import os
import re
import time
import urllib.request
import urllib.error


# ======================================================================
# 配置区 —— 换模型 / 换厂商只改这里
# ======================================================================
CONFIG = {
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key_env": "ZHIPU_API_KEY",   # 密钥从环境变量读，绝不写进代码

    # 文本模型：并发数越大越不容易被限流。
    # 实测（2026-10-13）：glm-4.7-flash 并发 1，连续调用必 429；
    #   glm-4-flash-250414 并发 5，抽取任务质量一样，稳得多。
    #   两个都是免费，所以「换模型」这个动作是零成本的调优手段。
    "text_model": "glm-4-flash-250414",   # 并发 5
    # 备用：并发更高时才换（见 FALLBACK_MODELS）
    "text_model_fallback": "glm-4.5-flash",

    "vision_model": "glm-4v-flash",     # 图片识别（免费，并发 10）
    "vision_max_tokens": 1024,          # ★ 该模型硬上限 1024，传更大直接 400
    "text_max_tokens": 2000,
    "timeout": 90,                      # 秒
    "max_retries": 3,
}

# 429 重试时按顺序换模型（都是免费模型，换了不花钱）
FALLBACK_MODELS = ["glm-4-flash-250414", "glm-4.5-flash", "glm-4.7-flash"]


class AIError(Exception):
    """所有 AI 相关错误的统一类型。

    code 取值与 docs/api-contract.md 第 0 节的错误码一一对应：
      NO_API_KEY / AI_TIMEOUT / AI_BUSY / AI_BAD_OUTPUT
    """

    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


# ======================================================================
# 底层调用
# ======================================================================
def _api_key():
    """从环境变量取密钥。取不到就抛 NO_API_KEY（契约里定义了这个错误码）。"""
    key = os.environ.get(CONFIG["api_key_env"])
    if not key:
        raise AIError(
            "NO_API_KEY",
            "服务未配置 AI 密钥",
            hint=f"请在云函数环境变量中设置 {CONFIG['api_key_env']}",
        )
    return key


def _post(payload, retry_on_429=True, model_switchable=True):
    """发一次请求。

    ★ 坑 2 的处理策略（实测调出来的）：
      免费模型并发很低（glm-4.7-flash 只有 1），429 是常态。
      最初的做法是「退避后用同一个模型重试」，结果一次请求拖到 88 秒——
      因为退避的等待 + 被限流模型的排队时间叠加起来太长。

      改成【429 就换一个并发更高的免费模型】，而不是干等：
        - 换模型是零成本的（都是免费模型）
        - 不同模型的并发池是独立的，换一个就绕开了排队
      这比退避快得多，实测把88 秒降到了正常范围。
    """
    url = CONFIG["base_url"] + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + _api_key(),
    }

    tried = set([payload.get("model")]) if model_switchable else set()
    last_err = None

    for attempt in range(CONFIG["max_retries"]):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=CONFIG["timeout"]) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"].get("content") or ""
            # ★ 坑 1：content 可能是空字符串（内容跑到 reasoning_content 里去了）。
            #   空内容在解析场景下等于失败，要明确报出来而不是返回空结果。
            return content

        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]

            if e.code == 429 and attempt < CONFIG["max_retries"] - 1:
                # 先试换模型（并发池不同，可能就不限流了），换不到再退避
                switched = False
                if model_switchable:
                    for m in FALLBACK_MODELS:
                        if m not in tried:
                            payload["model"] = m
                            tried.add(m)
                            switched = True
                            break
                if not switched:
                    time.sleep(1 + attempt)   # 都试过了，才退避（比原来短很多）
                continue

            if e.code == 429:
                raise AIError(
                    "AI_BUSY",
                    "AI 服务繁忙，请稍后重试",
                    hint="免费模型并发有限，稍等几秒再试",
                )
            if e.code in (401, 403):
                raise AIError(
                    "NO_API_KEY",
                    "AI 密钥无效或已失效",
                    hint=f"检查环境变量 {CONFIG['api_key_env']}",
                )
            if detail:
                raise AIError("AI_BAD_OUTPUT", f"AI 调用失败（{e.code}）：{detail[:120]}")
            raise AIError("AI_BAD_OUTPUT", f"AI 调用失败（{e.code}）")

        except urllib.error.URLError as e:
            last_err = e
            if attempt < CONFIG["max_retries"] - 1:
                time.sleep(2 ** attempt + 1)
                continue
            raise AIError("AI_TIMEOUT", "连接 AI 服务超时")

    raise AIError("AI_TIMEOUT", "AI 服务无响应", hint=str(last_err))


# ======================================================================
# 能力 1：文本对话
# ======================================================================
def chat(prompt, max_tokens=None):
    """纯文本对话。给 AI 一段提示词，拿回一段文字。"""
    payload = {
        "model": CONFIG["text_model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens or CONFIG["text_max_tokens"],
        "temperature": 0.1,               # 低温度：抽取任务要稳定不要发挥
        "thinking": {"type": "disabled"},  # ★ 坑 1：必须显式关，否则 content 为空
    }
    return _post(payload)


# ======================================================================
# 能力 2：图片识别
# ======================================================================
def vision(image_bytes, prompt, mime="image/png"):
    """识别图片里的文字。★ 只做转录，不做任务提取。

    为什么要单独一个函数、且不做提取？
      实测（2026-10-10）：让 glm-4v-flash 边识别边提取，任务会被截断漏掉。
      所以这里只把图片变成文字，提取交给 parse_tasks()，
      文字路径与图片路径在「拿到文字」之后汇合成同一条流程。
    """
    import base64

    b64 = base64.b64encode(image_bytes).decode("ascii")
    content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": prompt},
    ]
    payload = {
        "model": CONFIG["vision_model"],
        "messages": [{"role": "user", "content": content}],
        # ★ 坑 3：vision 模型的 max_tokens 上限就是 1024，传 2000 会 HTTP 400
        "max_tokens": CONFIG["vision_max_tokens"],
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
    }
    return _post(payload)


OCR_PROMPT = (
    "这是手机通知截图或聊天记录截图。"
    "请把图中所有文字原样转录出来，每条消息一行，格式：发送人: 内容\n"
    "只转录，不要总结、不要分析、不要添加图中没有的内容。"
)


def ocr(image_bytes, mime="image/png"):
    """图片 → 文字。识别失败时抛 AI_ERROR。"""
    text = vision(image_bytes, OCR_PROMPT, mime)
    if not text or not text.strip():
        raise AIError(
            "AI_BAD_OUTPUT",
            "没能从图片中识别出文字",
            hint="试试更清晰的截图，或确认图片里确实有文字",
        )
    return text


# ======================================================================
# 能力 3：JSON 清洗
# ======================================================================
def parse_json(text):
    """把模型返回的文字变成 JSON 对象。

    ★ 坑 4：模型返回常带markdown 代码块包裹（```json ... ```），
      json.loads 直接抛错。而且【行为不稳定】——实测有时裹有时不裹，
      所以清洗逻辑任何时候都不能省。
    """
    if not text:
        raise AIError("AI_BAD_OUTPUT", "AI 返回内容为空")

    t = text.strip()

    # 剥掉 ``` 或 ```json 开头的围栏
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    t = t.strip()

    # 若中间夹着解释文字，只取第一个 [ 到最后一个 ] 之间的部分
    i, j = t.find("["), t.rfind("]")
    if i >= 0 and j > i:
        t = t[i : j + 1]

    # 若模型把对象包成了 {"tasks":[...]}，把里面的数组取出来
    try:
        obj = json.loads(t)
        if isinstance(obj, dict) and "tasks" in obj:
            return obj["tasks"]
        if isinstance(obj, dict) and "data" in obj:
            return obj["data"]
        return obj
    except json.JSONDecodeError:
        # 还有一层：直接用正则捞出所有 {...} 块
        blocks = re.findall(r"\{[^{}]*\}", t, re.S)
        if blocks:
            try:
                return [json.loads(b) for b in blocks]
            except json.JSONDecodeError:
                pass
        raise AIError(
            "AI_BAD_OUTPUT",
            "AI 返回的内容无法解析",
            hint="这通常是 AI 没按格式输出，重试一次通常就好了",
        )


# ======================================================================
# 能力 4：任务提取（★ 业务核心）
# ======================================================================
# 这个提示词是【实测调出来的】，不是凭空写的。改动请重跑验证。
#   第一版只写了「不要提取闲聊」，漏掉了「@我 私信」这条真任务；
#   加了正反例之后才对。正反例都要有，光写禁止项不够。
EXTRACT_PROMPT = """从下面聊天记录里提取「需要用户本人要去做」的任务。

【必须提取】
- 带 @我 / @你 / @所有人，且用户需要采取行动的事
- 含明确截止时间或动作要求的事
- ★ 指向用户本人、需要用户去「查看 / 确认 / 回复 / 处理」某件事的话
  （例如「答案我发你私信了，记得看」「你看下这个文件」「记得回我一下」）
  ——这类话没有时间、也不是动作要求，但【一定要提出来】，漏了用户就会误事

【必须忽略】
- 纯闲聊、表情、水群（例如「哈哈哈」「+1」「[表情]」「中午吃啥」）
- 只是告知规则变更、没有要求用户行动的信息
  （例如「从下周起打卡改到 21:00」—— 这是通知，不是任务）
- 他人之间的事，与用户无关

【时间】
原样保留原文表述到 time_raw；原文没写时间就填 null，严禁编造。

【标题】
简明扼要，一眼能看懂要做什么，不是原文照抄。

只输出 JSON 数组，不要 markdown 代码块，不要任何解释文字。
格式：[{{"title":"简短标题","time_raw":"原文时间或null","detail":"简短要求"}}]

记录：
{raw}"""


def parse_tasks(raw_text):
    """从文本提取任务列表。

    返回：list[dict]，每项 {title, time_raw, detail}
    失败：抛 AIError
    """
    if not raw_text or not raw_text.strip():
        raise AIError("EMPTY_INPUT", "内容为空，请先粘贴文字或上传图片")

    prompt = EXTRACT_PROMPT.replace("{raw}", raw_text)
    result = parse_json(chat(prompt))

    if not isinstance(result, list):
        raise AIError("AI_BAD_OUTPUT", "AI 返回的任务格式不正确")

    # 逐项清洗：模型可能给 null 或缺字段，这里补成安全值
    cleaned = []
    for item in result:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            # 标题为空的任务直接丢掉：数据库有 NOT NULL 约束，脏数据不许进
            continue
        detail = item.get("detail") or ""
        if not isinstance(detail, str):
            detail = str(detail)

        # ★ 实测发现的坑（2026-10-13）：模型经常把「没有时间」输出成
        #   字符串 "null" 或 "无"/"N/A"，而不是 JSON 的 null。
        #   实测复现：time_raw 拿到的是字符串 'null'，直接入库就是脏数据
        #   （用户会看到「截止时间：null」这种鬼东西）。
        #   所以这些"假 null"字面量一律转成真正的 None。
        NULL_LITERALS = {"null", "none", "n/a", "na", "无", "没有", "nil", "-", "未指定"}
        time_raw = item.get("time_raw")
        if isinstance(time_raw, str):
            time_raw = time_raw.strip()
            if not time_raw or time_raw.lower() in NULL_LITERALS:
                time_raw = None
        elif time_raw is not None:
            # 数字/布尔等异常类型，转成字符串再判断
            time_raw = str(time_raw).strip() or None

        cleaned.append({"title": title, "time_raw": time_raw, "detail": detail})

    return cleaned


def parse_tasks_from_image(image_bytes, mime="image/png"):
    """图片 → 任务列表（两步：先识图，再走和文字完全一样的提取流程）。

    这就是契约 §2 说的「两步法」，实测比一步准确。
    """
    text = ocr(image_bytes, mime)          # 第一步：图片 → 文字
    return text, parse_tasks(text)        # 第二步：文字 → 任务（与 §1 同一条路径）