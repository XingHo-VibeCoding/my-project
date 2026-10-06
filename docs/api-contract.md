# api-contract.md · 接口契约

> 前后端对接口的唯一依据。**改接口前先改这份文档**，再改代码。
> Day 15 建立；Day 16–20 逐条补齐业务接口。

**当前进度**：第1 节通用约定 ✅｜第 2 节 `/api/health` ✅｜第 3 节 `/api/timeline` ✅｜第 4 节 `/api/inbox` ✅｜第 5 节 待定义（Day 18–20）

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

## 3. GET /api/timeline（已上线 · Day 17）

**用途**：时间线页面数据源。返回 AI 判定为 `important` 的重要事项（F2 → F4）。
只取 `reminders` 表里 `importance='important'` 的行，通过 `message_id` 关联带回消息原文。

**请求**：`GET /api/timeline?limit=<数字>`

| 参数 | 必填 | 说明 |
|---|---|---|
| `limit` | 否 | 返回条数，默认 `20`，上限 `100`。非法值（`abc` / `0` / 负数）按 `20` 处理，小数向下取整 |

**成功 200**

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | boolean | 恒为 `true` |
| `service` | string | 固定 `group-reminder` |
| `fn` | string | 固定 `api-timeline` |
| `env` | string | 平台注入 |
| `count` | number | 本次返回条数 |
| `data` | array | 事项列表，每项 8 个字段（见下） |

`data[]` 字段：

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `id` | number | messages | 消息 ID |
| `importance` | string | reminders | 固定 `important`（本接口只出重要的） |
| `group_name` | string | messages | 群名 |
| `sender` | string | messages | 发送人 |
| `content` | string | messages | 消息原文 |
| `summary` | string | reminders | 判定摘要（F2 产出） |
| `deadline` | string | reminders | **自然语言短语**（如 `22:00`），不是时间戳 |
| `received_at` | string | messages | ISO 8601 UTC，带 `Z` |

排序：`deadline` 升序（空值排最后）→ `created_at` 降序。

> `deadline` 保持自然语言短语是**有意的**：换算成剩余时间由前端 `message-card.js` 负责（Day 8 起就是这个约定）。改这一条要同步改整套卡片。

**失败**

| 状态码 | error | 场景 |
|---|---|---|
| 405 | `METHOD_NOT_ALLOWED` | 用了非 GET |
| 500 | `DB_UNAVAILABLE` | 查库失败，`code` 里带真实原因（如 `NO_API_KEY` / `HTTP_500`），`message` 已脱敏 |

---

## 4. GET /api/inbox（已上线 · Day 17）

**用途**：收件箱页面数据源。返回群消息原文（F1），每条附带它的判定结果。

**请求**：`GET /api/inbox?limit=<数字>`，参数同上。

**成功 200**

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | boolean | 恒为 `true` |
| `service` / `fn` / `env` | string | 同上，`fn` 固定 `api-inbox` |
| `count` | number | 本次返回条数 |
| `data` | array | 消息列表 |

`data[]` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | number | 消息 ID |
| `group_name` | string | 群名 |
| `sender` | string | 发送人 |
| `content` | string | 消息原文 |
| `received_at` | string | ISO 8601 UTC，带 `Z` |
| `parse_status` | string | 解析状态（`ok` / 失败标记） |
| `importance` | string \| **null** | `important` / `chat`；**还没判定过就是 `null`** |

排序：`received_at` 降序（最新在上）。

> **未判定的消息照样出现在列表里**（`importance: null`）。把「还没处理」当成「不存在」是最容易犯的错——前端必须能处理 `null` 这一列。

**失败**：同`/api/timeline`（405 / 500 `DB_UNAVAILABLE`）。

---

## 5. 待定义接口（Day 18–20 补齐，本节只占位）

> 下表只登记「有什么、哪天做」，**字段一律没定**，到时候连字段一起补进来。

| 路径 | 方法 | 用途 | 计划在 | 状态 |
|---|---|---|---|---|
| （写接口） | POST | 落库 / 更新判定结果 | Day 18–19 | 待定义 |
| 跨域配置 | — | HTTP 访问服务里配 CORS，前端才允许发请求 | Day 20 | 待定义 |

---

## 6. 变更记录

- 2026-10-04（Day 15）：建立本文档；落地 `GET /api/health`（已公网可访问）；登记待定义接口 4 项；写明跨域 Day 20 才做。
- 2026-10-06（Day 17）：补齐 `GET /api/timeline` 与 `GET /api/inbox` 完整契约（字段表 / 排序 / limit 规则 / 错误形状）；确认两者与 `MOCK_TIMELINE` 字段名逐字对应，第3 周换真数据前端不用改。
