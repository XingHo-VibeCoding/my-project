"""F3 精选推送 — ntfy 通道（Day 7 留桩，Day 12 定案）

为什么是 ntfy、不是 Bark（Day 12 更正）：
    接收机是**安卓手机**，Bark 官方仅支持 iOS，方案当场出局。
    ntfy 是「一次 HTTP POST 即送达」，与 Bark 同类，但安卓可用。

你拍板：F3 留桩。函数写好、只对 important 项触发、但不配置真机主题。
接真机那天：手机装 ntfy App -> 订阅一个私有主题 -> 把主题名填进 NTFY_TOPIC 即可。

★ 迁移注意（本文件仍是 Bark 时代的骨架，只改了注释）：
    Bark 的 JSON 是 {"title": ..., "body": ...}
    ntfy 的 JSON 是 {"title": ..., "message": ...}  ← 字段名不同
    下方 post() 里的 "body" 在真正启用 ntfy 时**必须改成 "message"**。
"""
import httpx

# ntfy 公共服务器（https://ntfy.sh）；用私有主题名，别人猜不到就不会收到
NTFY_SERVER = "https://ntfy.sh"
# ★ 私有主题名：接入时填自己的（如 "my-secret-topic-123"），空 = 不推送
# TODO(Day 18–19)：填入后，下方 post() 的 json 字段要同步从 body 改成 message
NTFY_TOPIC = ""


def push_important(group_name: str | None, summary: str) -> dict:
    """只对判定为 important 的消息调用（F3-1：闲聊一条不推）。"""
    if not NTFY_TOPIC:
        return {"pushed": False, "reason": "ntfy 主题未配置（留桩中）"}
    title = f"重要：{group_name or '私聊'}"
    url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    try:
        # ⚠️ 这里还是 Bark 的字段名，启用 ntfy 前必须改成 "message"
        resp = httpx.post(url, json={"title": title, "body": summary}, timeout=10)
        return {"pushed": True, "http_status": resp.status_code}
    except Exception as exc:  # 推送失败不拖垮主链路
        return {"pushed": False, "reason": f"ntfy 请求失败: {exc}"}