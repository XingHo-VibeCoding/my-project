# legacy/ — 旧版代码归档（已废弃）

> **这里的一切都不再维护、不再运行、不再开发。**
> 仅作为**历史记录**保留，供将来查阅技术经验。

## 归档原因

旧版项目是「群消息智能提醒助手」，靠**读取手机通知栏**自动捕获群消息。2026-10-10 判定该方向不可行，整个项目改版为「AI 日程整理工具」。

**不可行的实测记录**（这是本次改版的直接触发原因）：

| 问题 | 实测情况 |
|---|---|
| 接收端 APK 下不到 | ntfy 的 APK 只挂 GitHub Releases，本机实测 **HTTP 000 超时** |
| 发送端要装 App | SmsForwarder 需要用户自行安装配置 |
| 网络要打通 | 后端须监听 `0.0.0.0` + 内网穿透，手机才能连上电脑 |
| 权限敏感 | 读取其他 App 通知，隐私投诉与应用商店审核风险高 |

**任一环节装不上，整条链路就失效** —— 而这三个环节**没有一个能在当天搞定**。

## 目录内容

| 路径 | 是什么 | 可复用的经验 |
|---|---|---|
| `legacy/app/` | FastAPI 后端（F1 接收解析 / F2 规则引擎 / F3 推送桩 / F4 三视图） | 规则引擎 `judge.py` 的时间短语解析逻辑、倒计时算法 |
| `legacy/cloudfunctions/` | CloudBase 云函数（api-health / api-timeline / api-inbox） | **CloudBase 部署踩坑全套**：esbuild 打包、干净目录部署、环境变量推送 |
| `legacy/db/` | 旧表结构 `messages` / `reminders` + 12 条种子数据 | 表设计的注释写法值得沿用 |
| `legacy/skills/` | 筛选交互校验 Skill | 纯函数校验思路可用 |
| `legacy/web/` | 前端 mock 静态页 | 卡片组件、四种状态处理 |
| `../PRD_LEGACY.md` | 旧版 PRD 原文 | — |
| `../TECH_DESIGN_LEGACY.md` | 旧版技术方案原文 | — |
| `../research_LEGACY.md` | 旧版路线研究原文 | **最有价值的部分**：为什么「读安卓通知栏」是当时唯一可行路 |

## 新版怎么跑

旧版**已经不能运行了**（依赖已废弃的 API Key、需要穿透网络）。新版从`PRD.md` 重新开始。

**旧数据库表（`messages` / `reminders`）保留在CloudBase 中不删** —— 那是历史数据，也是验证新版数据链路是否正常的对照组。

## 启用了哪条经验

新版技术方案（`TECH_DESIGN_V2.md`）直接吸收了这些：

1. **CloudBase 云函数部署四步法**（干净目录 → 装依赖 → esbuild 单文件 → `--install-dependency false`）
2. **接口契约先写文档再写代码**（`docs/api-contract.md` 的做法）
3. **纯逻辑用 node 离线脚本验算**，不靠肉眼
4. **环境变量核验必须 `fn env pull`**，不能信 `config diff` 的显示
