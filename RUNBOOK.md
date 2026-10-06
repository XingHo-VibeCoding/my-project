# 运行说明 — 群消息智能提醒助手（Day 7 MVP）

> 本文件回答一个问题：**怎么把第一版跑起来**。所有命令在仓库根目录执行。

---

## 零、设备前提：全程按安卓手机设计（本产品的硬约束）

**这个产品只做安卓，iPhone 不在支持范围内。** 后续所有测试、截图、验收都按安卓来。

| 环节 | 为什么必须是安卓 | 后果 |
|---|---|---|
| 消息捕获 | iOS 不允许读取其他App 的通知 | **iPhone 整条路不成立**，不是「暂不支持」 |
| 捕获工具 SmsForwarder | 安卓开源 App，无需 root | iOS 无对应工具 |
| 推送接收| Bark 仅 iOS → 已出局，**改用 ntfy**（安卓可用） | ntfy 同样是一次 HTTP POST，方案形态不变 |
| 实机验证 | 同伴手机是安卓；窄屏地址栏会截断 | **截图不必强求完整 URL**，能证明「手机能打开 + 数据正确」即可 |

**验收标准按设备条件调整**：清单里写「图里要有地址栏」这类要求，若在手机上做不到（浏览器截断），换一个等效证据即可 —— 不要为了凑形式要求换设备重做。

**别再选型 iOS 工具**：看到 Bark、Server 酱（依赖 iOS 推送）、依赖 iOS 通知权限的方案，直接排除，不用再论证。

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
| F3 推送 | `app/notify.py` 留桩 | `NTFY_TOPIC` 为空不推；接真机时手机装 ntfy、填私有主题名即可（**JSON 字段要改成 `message`**，见第六节） |
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
- F3 推送留桩（**通道是 ntfy**，见下方「设备前提」；`NTFY_TOPIC` 为空即不推）
- 穿透工具选型（TECH_DESIGN 2.4 留到今天定但清单未列）：ngrok 零门槛 / Cloudflare Tunnel 有域名时升级
- 截止时间目前提取「22:00」这类时刻短语，倒计时以当天为基准演示；绝对日期换算留 DeepSeek 版（它最擅长）

> 2026-09-27 更正：F3 推送通道改用 **ntfy**（Bark 仅 iOS，接收机是安卓）。改 ntfy 时 `notify.py` 的 JSON 字段 `body` 要改成 `message`。

---

## 七、云端（CloudBase，Day 15/17 起）

> 本机（第五节的 FastAPI）与云端（这一节）是**两套并行的东西**：本机跑带 F1/F2 逻辑的完整应用，云端目前只有读接口。别混。

### 公网地址

| 用途 | 地址 |
|---|---|
| 云函数基址 | `https://felix-41414-d1g6voa3qf2ec166b-1499376110.ap-shanghai.app.tcloudbase.com` |
| 静态站（mock 页） | `https://felix-41414-d1g6voa3qf2ec166b-1499376110.tcloudbaseapp.com` |
| 环境 ID | `felix-41414-d1g6voa3qf2ec166b` |

### 现成的接口

```bash
BASE="https://felix-41414-d1g6voa3qf2ec166b-1499376110.ap-shanghai.app.tcloudbase.com"

curl -s --ssl-no-revoke "$BASE/api/health"     # 探活，应返 env=你的环境 ID
curl -s --ssl-no-revoke "$BASE/api/timeline"   # 时间线，4 条 important
curl -s --ssl-no-revoke "$BASE/api/inbox"      # 收件箱，12 条（important 4 / chat 8）
```

`curl` 的 `--ssl-no-revoke` 必需（本机证书吊销检查拿不到状态），**git 用等价的两参数**：
`-c http.sslBackend=schannel -c http.schannelCheckRevoke=false`。

### 验证「真的在读库」

改数据库里任意一条消息的 `content`，再打一次接口看是否返回新内容。**这是唯一能证明没走缓存的办法**（Day 17 用这招验过）。

### 数据库调试（不用开控制台）

```bash
TCB="C:/Users/Lenovo/.workbuddy/binaries/node/versions/22.22.2/node.exe"
CLI="C:/Users/Lenovo/.workbuddy/binaries/node/workspace/node_modules/@cloudbase/cli/bin/tcb"

"$TCB" "$CLI" db execute -e felix-41414-d1g6voa3qf2ec166b --sql "SELECT id, sender, content FROM messages LIMIT 5"
```

### 部署云函数（改代码后）

**必须在仓库外的干净目录部署**，否则 CLI 会把整个仓库（34M 的 `.venv`）当代码包上传 → 云端报 `InvalidParameter.ZipCodeFmt`。

脚本在会话 tmp（不入库），流程固定四步：拷源码到暂存目录 → 装依赖 → esbuild 打成单文件 → `--install-dependency false` 部署。

### 环境变量

读接口需要 `DB_API_KEY`（服务端 API Key，在控制台「环境管理 → API Key 配置」创建）。

```bash
# 推环境变量（该命令是交互式的，printf 喂默认项非交互执行）
printf '\n\n' | "$TCB" "$CLI" config update fn api-timeline -e <envId>

# 核验：必须用 fn env pull，config diff 的键名显示有bug（会把 DB_API_KEY 显示成 dB_API_KEY）
"$TCB" "$CLI" fn env pull api-timeline -e <envId> --output-file ./env.json
```

**Key 只放环境变量，绝不进仓库**。`tcb fn env` 只有 `pull`，没有 `set`。

### 这几条会踩坑

- **`event.path` 恒为 `/`** —— HTTP 访问服务转给事件函数时不传真实路径，**不能靠 path 路由**，一个函数只干一件事
- **免费体验版不能pg 内网直连** —— 连 `29.104.9.68:50331` 会超时，读库要走官方 HTTP API（零依赖，Node 自带 fetch）
- **有第三方依赖必须 esbuild 打包成单文件**，云端装依赖会坏
- CLI 里的 tcb 需要在仓库外的干净目录跑，别在仓库根执行
