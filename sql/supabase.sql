-- YUK & CHES'S HOME
-- 在 Supabase Dashboard -> SQL Editor 中完整执行一次。
-- 应用只通过 Render 服务端的 service_role key 访问这些表。

create extension if not exists pgcrypto;

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  status text not null default 'active'
    check (status in ('active', 'deleted', 'rerolled', 'archived')),
  parent_id uuid references public.messages(id) on delete set null,
  deletion_reason text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.items (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  title text not null default '',
  content text not null default '',
  value numeric not null default 0,
  status text not null default 'active',
  happened_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.app_settings (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists messages_created_at_idx
  on public.messages (created_at);
create index if not exists messages_status_created_at_idx
  on public.messages (status, created_at);
create index if not exists items_kind_created_at_idx
  on public.items (kind, created_at desc);
create index if not exists items_status_created_at_idx
  on public.items (status, created_at desc);

alter table public.messages enable row level security;
alter table public.items enable row level security;
alter table public.app_settings enable row level security;

-- 不创建 anon/authenticated policy：浏览器不能直接读取私人数据。
-- Render 后端使用 service_role key，service_role 会绕过 RLS。

insert into storage.buckets (id, name, public, file_size_limit)
values ('home-attachments', 'home-attachments', false, 15728640)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit;

-- Storage 同样保持私有，不为 anon/authenticated 创建 policy。
-- 应用服务端负责上传，并为下载生成 1 小时有效的签名链接。
