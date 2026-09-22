"""F3 精选推送 — Bark 通道（Day 7 留桩，不接真机）

你今天拍板：F3 留桩。函数写好、只对 important 项触发、但不配置真机 key。
接真机那天：手机装 Bark App -> 拿到设备 key -> 填进 BARK_URL 即可，其余不动。
"""
import httpx

# Bark 公共服务器（TECH_DESIGN 2.2）：换成自己的设备 key 即生效
BARK_URL = ""  # 例：https://api.day.app/你的设备key


def push_important(group_name: str | None, summary: str) -> dict:
    """只对判定为 important 的消息调用（F3-1：闲聊一条不推）。"""
    if not BARK_URL:
        return {"pushed": False, "reason": "Bark 未配置（Day 7 留桩）"}
    title = f"重要：{group_name or '私聊'}"
    try:
        resp = httpx.post(BARK_URL, json={"title": title, "body": summary}, timeout=10)
        return {"pushed": True, "http_status": resp.status_code}
    except Exception as exc:  # 推送失败不拖垮主链路
        return {"pushed": False, "reason": f"Bark 请求失败: {exc}"}
