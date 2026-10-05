-- Durable, user-owned conversation state for NexusAI.

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    display_name text not null,
    employee_role text not null default 'employee',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null default 'New conversation',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, user_id)
);

create index if not exists conversations_user_updated_idx
    on public.conversations (user_id, updated_at desc);

create table if not exists public.conversation_turns (
    id bigint generated always as identity primary key,
    conversation_id uuid not null,
    user_id uuid not null,
    user_request text not null,
    routed_to text[] not null,
    results jsonb not null,
    created_at timestamptz not null default now(),
    foreign key (conversation_id, user_id)
        references public.conversations(id, user_id) on delete cascade
);

create index if not exists conversation_turns_conversation_idx
    on public.conversation_turns (conversation_id, id);

create table if not exists public.pending_actions (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null,
    turn_id bigint not null references public.conversation_turns(id) on delete cascade,
    user_id uuid not null,
    agent_name text not null,
    payload jsonb not null,
    status text not null default 'pending'
        check (status in ('pending', 'executing', 'completed', 'cancelled')),
    expires_at timestamptz not null default (now() + interval '24 hours'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (conversation_id, user_id)
        references public.conversations(id, user_id) on delete cascade
);

create unique index if not exists one_open_pending_action_per_conversation
    on public.pending_actions (conversation_id)
    where status in ('pending', 'executing');

alter table public.profiles enable row level security;
alter table public.conversations enable row level security;
alter table public.conversation_turns enable row level security;
alter table public.pending_actions enable row level security;

drop policy if exists "profiles_own_row" on public.profiles;
create policy "profiles_own_row" on public.profiles
    for all to authenticated
    using ((select auth.uid()) = id)
    with check ((select auth.uid()) = id);

drop policy if exists "conversations_own_rows" on public.conversations;
create policy "conversations_own_rows" on public.conversations
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists "conversation_turns_own_rows" on public.conversation_turns;
create policy "conversation_turns_own_rows" on public.conversation_turns
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists "pending_actions_own_rows" on public.pending_actions;
create policy "pending_actions_own_rows" on public.pending_actions
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.profiles to authenticated;
grant select, insert, update, delete on public.conversations to authenticated;
grant select, insert, update, delete on public.conversation_turns to authenticated;
grant usage, select on sequence public.conversation_turns_id_seq to authenticated;
grant select, insert, update, delete on public.pending_actions to authenticated;

create or replace function public.create_profile_for_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
    insert into public.profiles (id, display_name)
    values (
        new.id,
        coalesce(new.raw_user_meta_data ->> 'display_name', split_part(new.email, '@', 1))
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists create_profile_after_signup on auth.users;
create trigger create_profile_after_signup
    after insert on auth.users
    for each row execute procedure public.create_profile_for_new_user();
