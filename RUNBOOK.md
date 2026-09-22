# 运行说明 — 群消息智能提醒助手（Day 7 MVP）

> 本文件回答一个问题：**怎么把第一版跑起来**。所有命令在仓库根目录执行。

---

## 一、首次准备（只做一次）

```bash
# 1. 创建虚拟环境（本机已有 Python 3.13，任选其一）
python -m venv .venv

# 2. 安装依赖
.venv\Scripts\pip install -r requirements.txt
```

> 依赖只有 4 个：fastapi / uvicorn / jinja2 / httpx。
> （Day 2 装的 Node.js 本版用不到——MVP 是纯 Python 后端 + Jinja2 模板，无前端构建链。）

## 二、日常启动

```bash
# 1. 启动服务（在仓库根目录）
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. 浏览器打开
http://localhost:8000
```

看到「📌 群消息智能提醒助手 — 重要事项时间线」页面即启动成功。

## 三、功能速览（MVP 四功能对 PRD）

| 功能 | 用法 | 说明 |
|---|---|---|
| F1 接收 | `POST /api/messages`，JSON 见下 | SmsForwarder 将来对接的端点；`GET /api/messages` 可看全部记录 |
| F2 判断 | 收到即自动判断（规则引擎版） | 12 条测试数据 12/12 判对；DeepSeek 升级位在 `app/judge.py` 末尾 |
| F3 推送 | `app/notify.py` 留桩 | `BARK_URL` 为空不推；接真机时手机装 Bark 填 key 即可 |
| F4 时间线 | 浏览器打开 `http://localhost:8000` | 带截止倒计时 + 无时限分组 |

## 四、测试数据（PRD 附录 A，验证 F1+F2+F4 全链路）

新开一个终端（服务别停），逐条贴入：

```bash
curl -X POST http://localhost:8000/api/messages -H "Content-Type: application/json" -d "{\"group_name\":\"学习打卡群\",\"sender\":\"班长\",\"content\":\"@所有人 本周五 22:00 前把作业提交到群里，过时不候\"}"

curl -X POST http://localhost:8000/api/messages -H "Content-Type: application/json" -d "{\"group_name\":\"学习打卡群\",\"sender\":\"老师\",\"content\":\"@我 你上次问的那道题，答案我发你私信了，记得看\"}"

curl -X POST http://localhost:8000/api/messages -H "Content-Type: application/json" -d "{\"group_name\":\"学习打卡群\",\"sender\":\"班长\",\"content\":\"提醒：从下周起打卡时间改到每晚 21:00，别记错\"}"

curl -X POST http://localhost:8000/api/messages -H "Content-Type: application/json" -d "{\"group_name\":\"学习打卡群\",\"sender\":\"老师\",\"content\":\"@所有人 明晚 20:00 线上答疑会，链接稍后发\"}"

curl -X POST http://localhost:8000/api/messages -H "Content-Type: application/json" -d "{\"group_name\":\"学习打卡群\",\"sender\":\"小王\",\"content\":\"哈哈哈哈今天好困\"}"
```

贴完刷新浏览器页面：前 4 条应出现在时间线（第 1 条带截止倒计时），最后一条闲聊**不该出现**。

## 五、其他端点

- `GET /api/health` — 服务自检
- `GET /api/messages` — 全部接收记录（含 parse_status）
- `GET /api/timeline` — 时间线原始 JSON
- `/docs` — FastAPI 自带交互文档

## 六、已知边界（今天不做，后续迭代）

- F2 为规则引擎版，DeepSeek 接入位已留（等 API key）
- F3 Bark 推送留桩（等手机装 Bark）
- 穿透工具选型（TECH_DESIGN 2.4 留到今天定但清单未列）：ngrok 零门槛 / Cloudflare Tunnel 有域名时升级
- 截止时间目前提取「22:00」这类时刻短语，倒计时以当天为基准演示；绝对日期换算留 DeepSeek 版（它最擅长）
