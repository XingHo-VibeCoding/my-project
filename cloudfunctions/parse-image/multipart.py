"""
multipart.py —— 从 event 里取出上传的图片（改版版· 一期）

======================================================================
为什么需要自己解析？
  实测（2026-10-17，探针函数 dump 出来的）：
    - CloudBase HTTP 访问服务**支持 multipart/form-data**，
      Content-Type 里的boundary 会完整传进 event.headers
    - 但整个 multipart 文本会被 **base64 编码**后放进 event.body
      （isBase64Encoded = True）
  所以链路是：
    event.body（base64） → 解base64 → 得到 multipart 原文
      → 按 boundary 切开 → 取出文件二进制
  ★ 没有现成的第三方库可用（云函数装依赖会坏），只能手写。

======================================================================
★ 踩坑记录
1. multipart 原文是【bytes】不是 str —— 里面混着图片二进制，
   强行 decode 会崩。必须全程用 bytes 处理，只有取文件名时才decode。
2. 图片二进制里可能出现恰好等于 boundary 的字节序列，
   所以必须用「前导换行 + boundary」这种标准分隔符来切，
   不能简单地 split(boundary)。
======================================================================
"""

import re
import base64
import binascii


class MultipartError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# 支持的图片类型 → MIME（PRD F2 要求 jpg/png/webp）
ALLOWED_MIME = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
}

# ★ 图片大小上限从 10 MB 降到 3 MB ——实测决定的，不是拍脑袋：
#   CloudBase HTTP 访问服务的请求体上限在 4~4.5 MB 之间
#   （实测：4 MB 通过，4.5 MB 返回 413 EXCEED_MAX_PAYLOAD_SIZE）
#   而 multipart 全文还要先 base64（膨胀 1.34 倍）才进 event.body，
#   所以 3 MB 原图 → base64 约 4.0 MB，刚好不撞上限，还留了余量。
#   PRD 第七节原写的「10 MB」是错的，实测后已修正。
MAX_IMAGE_BYTES = 3 * 1024 * 1024


def _decode_event_body(event):
    """把 event.body 还原成 bytes。"""
    body = event.get("body")
    if body is None:
        raise MultipartError("NO_FILE", "没有收到文件")

    if event.get("isBase64Encoded"):
        if isinstance(body, str):
            body = body.encode("ascii", errors="ignore")
        try:
            return base64.b64decode(body)
        except (binascii.Error, ValueError):
            raise MultipartError("BAD_BODY", "请求体解析失败")

    if isinstance(body, bytes):
        return body
    return str(body).encode("utf-8", errors="replace")


def _get_boundary(headers):
    """从 Content-Type 里抠出 boundary。"""
    ct = ""
    for k, v in (headers or {}).items():
        if str(k).lower() == "content-type":
            ct = str(v)
            break
    m = re.search(r"boundary=([^;]+)", ct, re.I)
    if not m:
        return None
    return m.group(1).strip().strip('"')


def parse_file(event):
    """从 event 里取出上传的图片。

    返回 dict: {filename, mime, content(bytes)}
    失败抛 MultipartError，code 与契约一致。
    """
    raw = _decode_event_body(event)
    boundary = _get_boundary(event.get("headers"))

    if not boundary:
        # 不是 multipart —— 允许直接传裸二进制（方便命令行调试）
        ctype = ""
        for k, v in (event.get("headers") or {}).items():
            if str(k).lower() == "content-type":
                ctype = str(v).split(";")[0].strip().lower()
        if ctype.startswith("image/"):
            _validate(ctype, len(raw))
            return {"filename": "upload", "mime": ALLOWED_MIME[ctype],
                    "content": raw}
        raise MultipartError(
            "BAD_BODY",
            "请用 multipart/form-data 上传文件（字段名 file）")

    bnd = ("--" + boundary).encode("utf-8")

    # ★ 用「前导换行 + boundary」切，不能直接 split(boundary)——
    #   图片二进制里可能刚好含有 boundary 字节序列。
    segments = raw.split(b"\r\n" + bnd)
    if len(segments) <= 1:
        # 第一个分片前面可能没有 \r\n，兜底再试一次
        segments = raw.split(bnd)
    if len(segments) <= 1:
        raise MultipartError("BAD_BODY", "文件内容格式不正确")

    for seg in segments:
        # 找 Content-Disposition 头与空行分隔出的 body
        head_end = seg.find(b"\r\n\r\n")
        if head_end < 0:
            continue
        head = seg[:head_end].decode("utf-8", errors="replace")
        # 尾部的 \r\n 属于分隔符，要去掉
        content = seg[head_end + 4:]
        if content.endswith(b"\r\n"):
            content = content[:-2]

        if 'filename=' not in head:
            continue        # 跳过普通字段

        m_name = re.search(r'filename="([^"]*)"', head)
        filename = m_name.group(1) if m_name else "upload"
        m_type = re.search(r"Content-Type:\s*([^\r\n]+)", head, re.I)
        mime = (m_type.group(1).strip().lower() if m_type else "")

        _validate(mime, len(content))
        return {"filename": filename or "upload",
                "mime": ALLOWED_MIME.get(mime, mime),
                "content": content}

    raise MultipartError("NO_FILE", "没有找到上传的文件")


def _validate(mime, size):
    """校验类型与大小。**先查类型再查大小** —— 类型不对就没必要报大小。"""
    if mime not in ALLOWED_MIME:
        raise MultipartError(
            "IMAGE_BAD_FORMAT",
            f"不支持的图片格式（{mime or '未知'}），请用 jpg / png / webp")
    if size <= 0:
        raise MultipartError("EMPTY_INPUT", "文件是空的")
    if size > MAX_IMAGE_BYTES:
        raise MultipartError(
            "IMAGE_TOO_LARGE",
            f"图片太大了（{size / 1024 / 1024:.1f} MB），"
            f"请控制在 {MAX_IMAGE_BYTES // 1024 // 1024} MB 以内")