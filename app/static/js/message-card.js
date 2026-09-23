/* ==========================================================================
   MessageCard —— 可复用消息卡片组件（Day 8 余力加练产物）
   --------------------------------------------------------------------------
   主视图里的「带截止时间」和「无时限」两个列表，都由这一个组件渲染：
   卡片长什么样、截止时间怎么算倒计时，全项目只写一份。

   第 3 周接真实接口时，本文件一行都不用改 —— 只要喂进来的数据字段名
   和 /api/timeline 一致（id / importance / summary / deadline /
   group_name / sender / content / received_at），换数据源即可。

   对外接口：
     MessageCard.render(item)          -> 一张卡片的 HTML 字符串
     MessageCard.skeleton(n)           -> n 个骨架屏占位卡（加载中状态用）
     MessageCard.empty(text)           -> 空状态提示块
     MessageCard.error(reason)         -> 错误状态块（自带「重试」按钮）
     MessageCard.startTimers(root)     -> 启动/刷新所有卡片的倒计时
     MessageCard.deadlineTarget(text)  -> 截止短语 -> Date（算不出返回 null）
   ========================================================================== */
(function (global) {
  "use strict";

  var WEEK_MAP = { "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0, "天": 0 };

  /* ---------- 1. 截止短语 -> 绝对时间 ----------
     规则引擎（F2）提取出来的是「今晚 21:00」「周五 22:00」这类短语，
     要做倒计时就得换算成具体时刻。这是 F4 页面的活，不是 AI 判断的活。 */
  function deadlineTarget(text) {
    if (!text) return null;
    var now = new Date();
    var hm = text.match(/(\d{1,2})\s*[:：]\s*(\d{2})/);
    var d = new Date(now);
    var offset = null;

    if (/今[天晚]/.test(text)) {
      offset = 0;
    } else if (/明[天晚]/.test(text)) {
      offset = 1;
    } else {
      // 周几的算法统一按「周一是一周第一天」：周一=1 … 周日=7
      var dowMon = now.getDay() === 0 ? 7 : now.getDay();
      var nextMonIn = ((8 - dowMon) % 7) || 7;          // 距离「下周一」还有几天
      var w = text.match(/([本下]?)周([一二三四五六日天])/);
      if (w) {
        var x = WEEK_MAP[w[2]] === 0 ? 7 : WEEK_MAP[w[2]];
        if (w[1] === "下") offset = nextMonIn + (x - 1);  // 下周五 = 下周一 + 4 天
        else if (x >= dowMon) offset = x - dowMon;        // 说「周五」时周五还没到 -> 本周五
        else offset = nextMonIn + (x - 1);                // 本周已经过了 -> 指下一周那天
      } else if (/下周/.test(text)) {
        offset = nextMonIn;                              // 「下周」没指明周几 -> 按下周一算
      }
    }

    if (offset === null && !hm) return null;   // 只有「3月5日」这类，暂不做倒计时

    if (offset !== null) d.setDate(d.getDate() + offset);
    if (hm) d.setHours(Number(hm[1]), Number(hm[2]), 0, 0);
    else d.setHours(23, 59, 0, 0);             // 只给了「周五」没给时刻，算当天末尾

    if (offset === null && d.getTime() < now.getTime()) {
      d.setDate(d.getDate() + 1);              // 只给了「21:00」且已过 -> 明天
    }
    return d;
  }

  /* ---------- 2. 剩余时间文案 ---------- */
  function countdownText(ms) {
    if (ms <= 0) return "已截止";
    var t = Math.floor(ms / 1000);
    var day = Math.floor(t / 86400);
    var hour = Math.floor(t % 86400 / 3600);
    var min = Math.floor(t % 3600 / 60);
    var sec = t % 60;
    var parts = [];
    if (day) parts.push("<span class=\"num\">" + day + "</span> 天");
    if (day || hour) parts.push("<span class=\"num\">" + hour + "</span> 小时");
    parts.push("<span class=\"num\">" + min + "</span> 分");
    if (!day) parts.push("<span class=\"num\">" + sec + "</span> 秒");
    return "剩 " + parts.join(" ");
  }

  /* ---------- 3. 转义：假数据里万一带了 < > 也不会把页面搞乱 ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---------- 4. 一张卡片 ---------- */
  function render(item) {
    item = item || {};
    var target = deadlineTarget(item.deadline);
    var badge = item.deadline
      ? "<span class=\"badge\">⏰ " + esc(item.deadline) + "</span>"
      : "<span class=\"badge chat\">无时限</span>";
    var countdown = target
      ? "<div class=\"countdown\" data-deadline=\"" + target.getTime() + "\">…</div>"
      : "";
    var origin = item.content
      ? "<details class=\"origin\"><summary>看原文</summary><p>" + esc(item.content) + "</p></details>"
      : "";
    var meta = "收到 " + esc(item.received_at || "—") +
      " · 判定 " + esc(item.importance || "—") + "（F2 规则引擎）";

    return "<article class=\"card\">" +
      "<div class=\"top\">" +
        "<span class=\"who\">" + esc((item.group_name || "私聊") + " · " + (item.sender || "未知")) + "</span>" +
        badge +
      "</div>" +
      "<p class=\"what\">" + esc(item.summary || item.content || "（无内容）") + "</p>" +
      origin +
      countdown +
      "<p class=\"meta\">" + meta + "</p>" +
      "</article>";
  }

  /* ---------- 5. 加载中：骨架屏 ---------- */
  function skeleton(n) {
    var one = "<div class=\"sk-card\">" +
      "<div class=\"sk-line w60\"></div>" +
      "<div class=\"sk-line w90\"></div>" +
      "<div class=\"sk-line w40\"></div>" +
      "</div>";
    var out = "";
    for (var i = 0; i < (n || 1); i++) out += one;
    return out;
  }

  /* ---------- 6. 空状态 ---------- */
  function empty(text) {
    return "<div class=\"empty\">" + esc(text || "暂无内容") + "</div>";
  }

  /* ---------- 7. 错误状态 ---------- */
  function error(reason) {
    return "<div class=\"error-box\">" +
      "<p class=\"err-title\">⚠️ 时间线加载失败</p>" +
      "<p class=\"err-msg\">" + esc(reason || "未知错误") + "</p>" +
      "<button type=\"button\" data-retry>重试</button>" +
      "</div>";
  }

  /* ---------- 8. 倒计时走秒 ---------- */
  function tick() {
    var list = document.querySelectorAll(".countdown[data-deadline]");
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      el.innerHTML = countdownText(Number(el.getAttribute("data-deadline")) - Date.now());
    }
  }

  var timer = null;
  function startTimers() {
    tick();
    if (timer === null) timer = global.setInterval(tick, 1000);
  }

  function stopTimers() {
    if (timer !== null) { global.clearInterval(timer); timer = null; }
  }

  global.MessageCard = {
    render: render,
    skeleton: skeleton,
    empty: empty,
    error: error,
    startTimers: startTimers,
    stopTimers: stopTimers,
    deadlineTarget: deadlineTarget,
    countdownText: countdownText
  };
})(window);
