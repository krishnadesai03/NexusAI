-- Anonymous, persona-scoped demo sessions for the public 0.4.0 experience.

create table public.demo_sessions (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique,
    persona_slug text not null,
    created_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    expires_at timestamptz not null,
    check (expires_at > created_at)
);

create index demo_sessions_expiry_idx on public.demo_sessions (expires_at);

-- A conversation has exactly one owner during the transition: either a legacy Supabase user or
-- an anonymous demo session. Persona is stored on demo conversations for durable audit context.
alter table public.conversations
    add column demo_session_id uuid references public.demo_sessions(id) on delete cascade,
    add column persona_slug text;
alter table public.conversations alter column user_id drop not null;
alter table public.conversations
    add constraint conversations_exactly_one_owner
        check ((user_id is null) <> (demo_session_id is null)),
    add constraint conversations_demo_persona_consistency
        check (
            (demo_session_id is null and persona_slug is null)
            or (demo_session_id is not null and persona_slug is not null)
        ),
    add constraint conversations_id_demo_session_key unique (id, demo_session_id);

create index conversations_demo_session_updated_idx
    on public.conversations (demo_session_id, updated_at desc)
    where demo_session_id is not null;

alter table public.conversation_turns
    add column demo_session_id uuid references public.demo_sessions(id) on delete cascade;
alter table public.conversation_turns alter column user_id drop not null;
alter table public.conversation_turns
    add constraint conversation_turns_exactly_one_owner
        check ((user_id is null) <> (demo_session_id is null)),
    add constraint conversation_turns_demo_conversation_fk
        foreign key (conversation_id, demo_session_id)
        references public.conversations(id, demo_session_id) on delete cascade;

create index conversation_turns_demo_owner_idx
    on public.conversation_turns (demo_session_id, conversation_id, id)
    where demo_session_id is not null;

alter table public.pending_actions
    add column demo_session_id uuid references public.demo_sessions(id) on delete cascade;
alter table public.pending_actions alter column user_id drop not null;
alter table public.pending_actions
    add constraint pending_actions_exactly_one_owner
        check ((user_id is null) <> (demo_session_id is null)),
    add constraint pending_actions_demo_conversation_fk
        foreign key (conversation_id, demo_session_id)
        references public.conversations(id, demo_session_id) on delete cascade;

create index pending_actions_demo_owner_idx
    on public.pending_actions (demo_session_id, conversation_id)
    where demo_session_id is not null;

-- Demo tokens are accepted only by the FastAPI backend. Browser-facing Supabase roles receive no
-- direct access to session rows; existing user-owned RLS policies remain unchanged.
alter table public.demo_sessions enable row level security;
revoke all on public.demo_sessions from anon, authenticated;
