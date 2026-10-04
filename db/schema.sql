-- ==========================================================================
-- db/schema.sql · 数据模型定义（Day 16）
-- --------------------------------------------------------------------------
-- 两张表，各管一件事：
--   messages   「原料」：群里收到的原始消息。不可再生 —— 过去的就是过去了，
--                        AI 判错了还能拿它重判一次。
--   reminders  「结论」：AI 对每条消息的判定结果。可重算 —— 换模型重跑时
--                        整表覆盖即可，不用去改原料。
--
-- 关联字段：reminders.message_id → messages.id（一条消息对一条判定）
--
-- 执行方式：CloudBase 控制台 → 数据库 → SQL 编辑器，粘贴本文件全部内容执行。
-- 本文件可重复执行（全部 IF NOT EXISTS / OR REPLACE），不会报错。
-- ==========================================================================


-- ==========================================================================
-- 表 1：messages —— 原始群消息（F1 落库）
-- ==========================================================================
CREATE TABLE IF NOT EXISTS messages (
    id            BIGSERIAL PRIMARY KEY,
    group_name    TEXT        NOT NULL,          -- 群名，如「学习打卡群」
    sender        TEXT        NOT NULL,          -- 发送人昵称，如「班长」
    content       TEXT        NOT NULL,          -- 消息原文，不做任何清洗
    received_at   TIMESTAMPTZ NOT NULL,          -- 消息到达本程序的时刻（带时区）
    parse_status  TEXT        NOT NULL DEFAULT 'ok',   -- 解析结果：ok / failed
                                                     -- PRD F1 验收 3：格式异常的消息
                                                     -- 也要留痕，不能让程序崩
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 入库时刻

    CONSTRAINT messages_parse_status_check
        CHECK (parse_status IN ('ok', 'failed'))
);

COMMENT ON TABLE  messages IS '原始群消息：SmsForwarder 转发的微信通知落库结果（F1）';
COMMENT ON COLUMN messages.id           IS '主键，自增；reminders.message_id 指向它';
COMMENT ON COLUMN messages.group_name   IS '群名，来自通知的「来自」字段';
COMMENT ON COLUMN messages.sender       IS '发送人昵称，来自通知的「发送人」字段';
COMMENT ON COLUMN messages.content      IS '消息正文原文，判定与展示都以它为准';
COMMENT ON COLUMN messages.received_at  IS '消息到达时间，用 TIMESTAMPTZ 带时区存，避免夏令时/时区歧义';
COMMENT ON COLUMN messages.parse_status IS 'ok=正常解析；failed=格式异常未能解析（PRD F1 验收 3 要求留痕）';
COMMENT ON COLUMN messages.created_at   IS '入库时刻，跟 received_at 分开：一个是消息发生时间，一个是落库时间';

-- 按时间倒序翻消息列表（Day 17 的 /api/inbox 会这么查）
CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages (received_at DESC);


-- ==========================================================================
-- 表 2：reminders —— AI 判定结果（F2 输出）
-- ==========================================================================
CREATE TABLE IF NOT EXISTS reminders (
    id           BIGSERIAL PRIMARY KEY,
    message_id   BIGINT      NOT NULL,           -- ★ 关联字段：指向 messages.id
    importance   TEXT        NOT NULL,           -- 判定三类：important / normal / chat
    summary      TEXT,                           -- 一句话要点（闲聊可为空）
    deadline     TEXT,                           -- 截止时间，存「自然语言短语」
    judged_by    TEXT        NOT NULL DEFAULT 'rule-engine',  -- 谁判的：rule-engine / deepseek
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- 关联与自增删：一条消息被删，它的判定结果跟着删，不留孤儿数据
    CONSTRAINT reminders_message_fk
        FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE,

    -- 三类判定值写死在数据库里，插错值直接报错，不给脏数据机会
    -- 取值必须是 app/judge.py 真正会输出的三个：important / normal / chat
    -- （PRD 文档里把 normal 那一类叫「一般」，代码里叫 normal，以代码为准）
    CONSTRAINT reminders_importance_check
        CHECK (importance IN ('important', 'normal', 'chat'))
);

COMMENT ON TABLE  reminders IS 'AI 重要性判定结果：important 重要 / normal 一般 / chat 闲聊（F2）';
COMMENT ON COLUMN reminders.id          IS '主键，自增';
COMMENT ON COLUMN reminders.message_id  IS '★ 关联字段：指向 messages.id，一条消息对应一条判定';
COMMENT ON COLUMN reminders.importance  IS 'important=重要（含任务/截止/@我）｜normal=一般（有价值但无需行动，PRD 叫「一般」）｜chat=纯闲聊表情。取值必须与 app/judge.py 输出一致';
COMMENT ON COLUMN reminders.summary     IS '一句话要点，重要项必填；闲聊项为空';
COMMENT ON COLUMN reminders.deadline    IS '截止时间，存「本周五 22:00」这类短语而不是时间戳 —— 前端 message-card.js 负责换算成倒计时（见 docs/api-contract.md 约定）';
COMMENT ON COLUMN reminders.judged_by   IS '判定来源：rule-engine=F2 规则引擎（Day 7）｜deepseek=后续接入大模型';
COMMENT ON COLUMN reminders.created_at  IS '本次判定完成的时间';

CREATE INDEX IF NOT EXISTS idx_reminders_message_id  ON reminders (message_id);
CREATE INDEX IF NOT EXISTS idx_reminders_importance ON reminders (importance);


-- ==========================================================================
-- 约束修正块（幂等）—— 为什么要专门写这一段？
--   表已经建过的情况下，再执行 CREATE TABLE IF NOT EXISTS 是【空操作】的，
--   改了文件里的 CHECK 也不会作用到已有的表上。所以这里主动做一次校正：
--   约束存在就先删掉，再按最新定义重建。可重复执行，不报错。
--
--   真实经过：Day 16 最初把第三类写成 'general'（照 PRD 文档「一般」），
--   但 app/judge.py 实际输出的是 'normal'。Day 16 学习者拍板：以代码为准。
-- ==========================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'reminders_importance_check'
           AND conrelid = 'reminders'::regclass
    ) THEN
        ALTER TABLE reminders DROP CONSTRAINT reminders_importance_check;
    END IF;

    ALTER TABLE reminders
        ADD CONSTRAINT reminders_importance_check
        CHECK (importance IN ('important', 'normal', 'chat'));
END $$;


-- ==========================================================================
-- Day 17 读接口的字段映射（现在就写死，别到时候再对）
-- --------------------------------------------------------------------------
-- /api/timeline 的返回项 = 下面这个 JOIN 的结果，字段名与前端
-- web/mock/index.html 里的 MOCK_TIMELINE 完全一致：
--
--   SELECT m.id            AS id,
--          r.importance    AS importance,
--          m.group_name    AS group_name,
--          m.sender        AS sender,
--          m.content       AS content,
--          r.summary       AS summary,
--          r.deadline      AS deadline,
--          m.received_at   AS received_at
--     FROM reminders r
--     JOIN messages m ON m.id = r.message_id
--    WHERE r.importance = 'important'
--    ORDER BY r.deadline NULLS LAST, m.received_at DESC;
--
-- 所以：【前端一行代码都不用改】，第 3 周换的只是数据来源。
-- ==========================================================================
