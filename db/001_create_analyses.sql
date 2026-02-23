create extension if not exists "pgcrypto";

create table if not exists public.analyses (
    analysis_id uuid primary key default gen_random_uuid(),
    user_id text not null,
    title text not null default 'Untitled Analysis',
    deck_data jsonb,
    insights jsonb,
    deep_research jsonb,
    memo jsonb,
    status text not null default 'draft' check (status in ('draft', 'completed')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_analyses_user_id_created_at
    on public.analyses (user_id, created_at desc);
