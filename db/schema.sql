-- ==========================================================================
-- db/schema.sql · 数据模型定义（改版版 · 2026-10-10）
-- --------------------------------------------------------------------------
-- ★ 本文件已在真实 CloudBase 数据库执行验证通过（2026-10-10）：
--   建表 / 索引 / 视图全部成功；4 条约束（非法枚举、空标题、
--   状态与完成时间不一致、图片超 10MB）均确认会正确拦截脏数据。
--
-- 对应需求：PRD.md「AI 日程整理工具」第四节 F4 标准日程表格输出
--
-- 与旧版（legacy/db/schema.sql）的区别：
--   旧版 messages + reminders ——「群里收到的消息」+「AI 的重要度判定」
--   新版 sources    + tasks    ——「用户上传的原始内容」+「提取出的日程任务」
--
-- 为什么换表而不复用（改版拍板决定 B）：
--   新产品的核心对象是「任务」，不是「消息」。字段含义完全不同：
--     旧 reminders.deadline 存「周五 22:00」这种自然语言短语，靠前端换算倒计时
--     新 tasks.deadline_at直接存绝对时间（TIMESTAMPTZ），相对表述在AI 解析阶段
--                        就已按录入当天换算完毕，不留到前端做时间推算
--   硬套旧表会导致字段语义错位，不如另起清晰的新结构。
--
-- ★ 旧表 messages / reminders **保留不删**（历史数据，也作为对照组）。
--
-- 执行方式：CloudBase 控制台 → 数据库 → SQL 编辑器，粘贴全部内容执行。
-- 本文件可重复执行（IF NOT EXISTS），不会报错。
-- ==========================================================================


-- ==========================================================================
-- 表 1：sources —— 用户上传的原始内容（F1/F2 输入落库）
-- ==========================================================================
-- 为什么要有这张表？
--   「原始输入」和「解析结果」必须分开存，原因有三个：
--     1. 可重解析：AI 抽错了要能拿原文重跑一遍，改模型后整批重算
--     2. 可追溯：用户能看到「系统是从哪段内容提取出这条任务的」
--     3. 不丢证据：原始内容永不因解析而丢失
--
-- 对应旧版的 messages 表，但语义更宽 —— 不再是「群消息」，
-- 而是「用户主动上传的任何内容」（一段文字 / 一张截图）。
-- ==========================================================================
CREATE TABLE IF NOT EXISTS sources (
    id              BIGSERIAL PRIMARY KEY,
    input_type      TEXT        NOT NULL,      -- 输入方式：text 粘贴文字 / image 上传截图
    raw_text        TEXT,                       -- OCR 识别出的文字；纯文本输入时等于原文
    image_path      TEXT,                       -- 图片存储路径；纯文本输入时为 NULL
    image_size      INTEGER,                    -- 图片字节数，用于校验是否超 10 MB 上限
    parse_status    TEXT        NOT NULL DEFAULT 'pending',
                                               -- pending 待解析 / ok 解析成功
                                               -- failed 解析失败（识别失败、AI 超时等）
                                               -- ★ 失败也要留痕，不能静默丢
    error_message   TEXT,                       -- 失败原因，给用户看的提示文案
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 用户上传时刻

    CONSTRAINT sources_input_type_check
        CHECK (input_type IN ('text', 'image')),

    CONSTRAINT sources_parse_status_check
        CHECK (parse_status IN ('pending', 'ok', 'failed')),

    -- 图片大小硬上限 10 MB（PRD 第七节：手机截图随手就 2-5 MB，10 MB 够用）
    CONSTRAINT sources_image_size_check
        CHECK (image_size IS NULL OR image_size <= 10485760)
);

COMMENT ON TABLE  sources IS '用户主动上传的原始内容：文字片段或截图（F1/F2 输入）';
COMMENT ON COLUMN sources.id            IS '主键，自增；tasks.source_id 指向它';
COMMENT ON COLUMN sources.input_type    IS 'text=粘贴文字｜image=上传截图（PRD F1/F2 双输入）';
COMMENT ON COLUMN sources.raw_text      IS 'OCR 识别出的文字；text 输入时为用户原文，image 输入时为识别结果';
COMMENT ON COLUMN sources.image_path    IS '图片存储路径；text 输入时为 NULL';
COMMENT ON COLUMN sources.image_size    IS '图片字节数；数据库层再挡一次 10 MB 上限';
COMMENT ON COLUMN sources.parse_status  IS 'pending=待解析｜ok=解析成功｜failed=解析失败（失败必须留痕）';
COMMENT ON COLUMN sources.error_message IS '失败原因；面向用户的提示文案，不要写内部堆栈';
COMMENT ON COLUMN sources.created_at    IS '用户上传时刻';

CREATE INDEX IF NOT EXISTS idx_sources_created_at  ON sources (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_parse_status ON sources (parse_status);


-- ==========================================================================
-- 表 2：tasks —— 提取出的日程任务（核心表 · PRD F4 统一字段）
-- ==========================================================================
-- PRD 规定的五个输出字段对应关系：
--   任务标题   → title
--   截止时间   → deadline_at（可为 NULL：AI 提不出时间时不猜，PRD 第三节）
--   任务详情   → detail
--   录入时间   → created_at
--   完成状态   → status
--
-- 额外字段（工程必需，不属于用户可见输出）：
--   source_id   追溯来自哪次上传
--   deadline_raw 保留原始时间表述，用于详情展示（如「下周一 14:00」原话）
--   parsed_by   哪个模型解析的，换模型重跑时能区分
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tasks (
    id              BIGSERIAL PRIMARY KEY,
    source_id       BIGINT,                    -- 关联：指向 sources.id；手动补录的条目为 NULL
    title           TEXT        NOT NULL,      -- ★ 任务标题（必填，唯一不可空字段）
    deadline_at     TIMESTAMPTZ,               -- ★ 截止/执行时间；无时间信息时为 NULL，不猜测
    deadline_raw    TEXT,                       -- 时间原始表述：「周五 22:00」「下周一14:00」
    detail          TEXT,                       -- ★ 任务详情：具体内容、要求、注意事项
    status          TEXT        NOT NULL DEFAULT 'pending',  -- ★ 完成状态
    parsed_by       TEXT        NOT NULL DEFAULT 'glm-4.7-flash',  -- 解析用的模型名
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),  -- ★ 录入时间
    completed_at    TIMESTAMPTZ,               -- 打卡完成时刻；未完成时为 NULL

    -- 来源删了，任务跟着删，不留孤儿数据
    CONSTRAINT tasks_source_fk
        FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE CASCADE,

    -- 只允许两种状态，写死在数据库里，插错值直接报错
    CONSTRAINT tasks_status_check
        CHECK (status IN ('pending', 'done')),

    -- 状态与完成时间必须一致：done 必须有时间戳，pending 必须没有
    -- 防止出现「标记完成了但没有完成时间」这种脏数据
    CONSTRAINT tasks_completed_consistency
        CHECK (
            (status = 'done'    AND completed_at IS NOT NULL) OR
            (status = 'pending' AND completed_at IS NULL)
        ),

    -- 标题不能是空白字符串
    CONSTRAINT tasks_title_not_blank
        CHECK (length(btrim(title)) > 0)
);

COMMENT ON TABLE  tasks IS 'AI 提取出的日程任务：这是本项目的核心表（PRD F4）';
COMMENT ON COLUMN tasks.id            IS '主键，自增';
COMMENT ON COLUMN tasks.source_id     IS '★ 关联 sources.id；用户手动补录的条目为 NULL（不来自任何上传）';
COMMENT ON COLUMN tasks.title         IS '★ 任务标题（PRD 五个字段之一）；数据库层禁止空白标题';
COMMENT ON COLUMN tasks.deadline_at   IS '★ 截止/执行时间（PRD 五个字段之二）；★ 无时间信息时为 NULL，不猜测';
COMMENT ON COLUMN tasks.deadline_raw  IS '时间原始表述原话（如「下周一 14:00」）；绝对时间算错了还能看出原话';
COMMENT ON COLUMN tasks.detail        IS '★ 任务详情（PRD 五个字段之三）：具体内容、要求、注意事项';
COMMENT ON COLUMN tasks.status        IS '★ 完成状态（PRD 五个字段之四）：pending 未完成 / done 已完成';
COMMENT ON COLUMN tasks.parsed_by     IS '解析该任务的模型名；换模型重跑时能区分新旧结果';
COMMENT ON COLUMN tasks.created_at    IS '★ 录入时间（PRD 五个字段之五）：任务进入表里的时刻';
COMMENT ON COLUMN tasks.completed_at  IS '打卡完成时刻；status=pending 时必须为 NULL（约束保证一致）';

-- 最常用查询：按状态看今日待办（未完成 + 有截止时间的排前面）
CREATE INDEX IF NOT EXISTS idx_tasks_status       ON tasks (status);
-- 按截止时间排序；NULL 排最后（未指定时间的沉到底部）
CREATE INDEX IF NOT EXISTS idx_tasks_deadline_at  ON tasks (deadline_at ASC NULLS LAST);
-- 按录入时间倒序（历史回溯：最近上传的在最前）
CREATE INDEX IF NOT EXISTS idx_tasks_created_at   ON tasks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_source_id    ON tasks (source_id);


-- ==========================================================================
-- 视图：当日待办总表（PRD F4「每日自动汇总一张当日待办总表」）
-- --------------------------------------------------------------------------
-- 为什么用视图而不是每次查？
--   「当日待办总表」是一个固定的业务概念（今天要做什么），
--   用视图固化下来：查询逻辑写一次，以后口径不会变。
--   不写进表是因为「今天」每天在变，存进表就得每天更新，是反模式。
-- ==========================================================================
CREATE OR REPLACE VIEW v_today_todo AS
SELECT
    t.id,
    t.title,
    t.deadline_at,
    t.deadline_raw,
    t.detail,
    t.status,
    t.created_at,
    t.completed_at
FROM tasks t
WHERE
    -- 截止时间落在今天的
    (t.deadline_at >= CURRENT_DATE
     AND t.deadline_at <  CURRENT_DATE + INTERVAL '1 day')
    -- 或者没有截止时间但今天录入的（手动补录的当日任务）
    OR (t.deadline_at IS NULL
        AND t.created_at >= CURRENT_DATE
        AND t.created_at <  CURRENT_DATE + INTERVAL '1 day')
ORDER BY
    -- 有时间的按时间排前面，没时间的沉底
    t.deadline_at ASC NULLS LAST,
    t.created_at DESC;

COMMENT ON VIEW v_today_todo IS '当日待办总表：有截止时间的按时间排，没时间的沉底（PRD F4）';


-- ==========================================================================
-- 与旧表的对照（改版说明，便于日后回溯）
-- ==========================================================================
--   旧 messages                →新 sources
--     group_name/sender/content   input_type/raw_text/image_path
--     received_at                 created_at
--     parse_status(ok/failed)     parse_status(pending/ok/failed)
--
--   旧 reminders              →  新 tasks
--     importance(important/normal/chat)  ★ 不再需要 —— 新版不分「重要度」，
--                                         只提取「任务」，全部都是要做的
--     summary                          title + detail（拆成两个明确字段）
--     deadline(自然语言短语)           deadline_at(绝对时间) + deadline_raw(原话)
--     message_id                       source_id
--     judged_by                        parsed_by
--
--   ★ 旧版 reminders 表保留在数据库中不删（历史数据 + 对照组），
--     但新版代码**一律不读不写**这两张旧表。
-- ==========================================================================
