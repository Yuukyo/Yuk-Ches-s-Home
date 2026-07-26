-- 可选：仅在你明确想清空本项目数据时执行。
-- 这是不可逆操作，默认不会被应用调用。
truncate table public.messages restart identity cascade;
truncate table public.items restart identity cascade;
truncate table public.app_settings restart identity cascade;
