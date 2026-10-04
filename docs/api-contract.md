# api-contract.md · 接口契约

> 前后端对接口的唯一依据。**改接口前先改这份文档**，再改代码。
> Day 15 建立；Day 16–20 逐条补齐业务接口。

---

## 0. 怎么写、怎么用

- 本文每个接口都写清：**请求怎么发、成功返回什么字段、出错返回什么**。
- 「已上线」= 公网能调通；「待定义」= 只占位，字段还没定，**不要照着写代码**。
- 字段命名统一 `snake_case`；时间统一 ISO 8601（UTC，带 `Z`）。

---

## 1. 通用约定

| 项 | 值 |
|---|---|
| 云函数基址（HTTP 访问服务） | `https://felix-41414-d1g6voa3qf2ec166b-1499376110.ap-shanghai.app.tcloudbase.com` |
| 前端静态站（静态网站托管） | `https://felix-41414-d1g6voa3qf2ec166b-1499376110.tcloudbaseapp.com` |
| 环境 ID | `felix-41414-d1g6voa3qf2ec166b` |
| 响应 Content-Type | `application/json; charset=utf-8` |
| 跨域（CORS） | **Day 20 才在「HTTP 访问服务」里配**；在此之前前端不发任何请求，`web/mock/index.html` 的数据全部写死在页面里 |

**错误响应的统一形状**（所有接口一致）：

```json
{ "ok": false, "service": "group-reminder", "fn": "<函数名>", "env": "<环境ID>", "error": "<错误码>" }
```

---

## 2. GET /api/health（已上线 · Day 15）

**用途**：公网探活。用来确认「域名 → HTTP 访问服务 → 云函数」这条链路是通的。

**请求**：`GET /api/health`，无参数、无请求体。

**成功 200**

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | boolean | 恒为 `true` |
| `service` | string | 服务名，本项目固定 `group-reminder` |
| `fn` | string | 函数名，本接口固定 `api-health` |
| `env` | string | **由平台运行时注入，代码里不写死** |
| `version` | string | 契约版本，当前 `1.0.0` |
| `ts` | string | 服务器时间，ISO 8601 UTC |

真实返回（2026-10-04 实测）：

```json
{"ok":true,"service":"group-reminder","fn":"api-health","env":"felix-41414-d1g6voa3qf2ec166b","version":"1.0.0","ts":"2026-10-04T15:19:53.810Z"}
```

**失败 405**（用了非 GET 方法）

```json
{"ok":false,"service":"group-reminder","fn":"api-health","env":"felix-41414-d1g6voa3qf2ec166b","error":"METHOD_NOT_ALLOWED"}
```

**怎么判断这次探活是真的**：看 `env` 是不是等于你的环境 ID `felix-41414-d1g6voa3qf2ec166b`。
地址能打开 ≠ 部署成功——域名是公用的，可能打开的是别人的地址或旧版本；`env` 是平台注入的，只有你自己环境里的这份代码才会回这个值。**这是公网地址第一次打开时第一个要确认的事。**

---

## 3. 待定义接口（Day 16–20 补齐，本节只占位）

> 下表只登记「有什么、哪天做」，**字段一律没定**，到时候连字段一起补进来。

| 路径 | 方法 | 用途 | 计划在 | 状态 |
|---|---|---|---|---|
| `/api/timeline` | GET | AI 判定后的重要事项列表（F2 → F4） | Day 17 | 待定义 |
| `/api/inbox` | GET | 群消息原文列表（F1） | Day 17 | 待定义 |
| （写接口） | POST | 落库 / 更新判定结果 | Day 18–19 | 待定义 |
| 跨域配置 | — | HTTP 访问服务里配 CORS，前端才允许发请求 | Day 20 | 待定义 |

**已知的形状约定**（来自 Day 8，第 3 周换真实数据源时组件不动）：

`/api/timeline` 的返回项字段名与页面里的 `MOCK_TIMELINE` 保持一致 ——
`id` / `importance` / `group_name` / `sender` / `content` / `summary` / `deadline` / `received_at`。
其中 `deadline` 是**自然语言短语**（如「今晚 21:00」「周五 22:00」），不是时间戳，
换算成倒计时由前端 `message-card.js` 负责——这一条不要轻易改，改了前端整套卡片都要跟着改。

---

## 4. 变更记录

- 2026-10-04（Day 15）：建立本文档；落地 `GET /api/health`（已公网可访问）；登记待定义接口 4 项；写明跨域 Day 20 才做。
