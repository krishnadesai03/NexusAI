-- Session-owned capture destination for public demo Slack/email actions.

create table public.demo_deliveries (
    id uuid primary key default gen_random_uuid(),
    demo_session_id uuid not null references public.demo_sessions(id) on delete cascade,
    persona_slug text not null,
    channel text not null check (channel in ('slack', 'email')),
    recipient text not null,
    subject text,
    content text not null,
    status text not null default 'captured' check (status = 'captured'),
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default (now() + interval '24 hours'),
    check (expires_at > created_at)
);

create index demo_deliveries_session_created_idx
    on public.demo_deliveries (demo_session_id, created_at desc);
create index demo_deliveries_expiry_idx on public.demo_deliveries (expires_at);

alter table public.demo_deliveries enable row level security;
revoke all on public.demo_deliveries from anon, authenticated;
