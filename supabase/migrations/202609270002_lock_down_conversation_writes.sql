-- The browser may read its own state through RLS, but only the trusted FastAPI backend writes
-- conversations, turns, pending actions, and authorization fields.

revoke all on public.profiles from authenticated;
revoke all on public.conversations from authenticated;
revoke all on public.conversation_turns from authenticated;
revoke all on public.pending_actions from authenticated;
revoke all on sequence public.conversation_turns_id_seq from authenticated;

grant select on public.profiles to authenticated;
grant update (display_name) on public.profiles to authenticated;
grant select on public.conversations to authenticated;
grant select on public.conversation_turns to authenticated;
grant select on public.pending_actions to authenticated;

drop policy if exists "profiles_own_row" on public.profiles;
create policy "profiles_read_own_row" on public.profiles
    for select to authenticated
    using ((select auth.uid()) = id);
create policy "profiles_update_own_name" on public.profiles
    for update to authenticated
    using ((select auth.uid()) = id)
    with check ((select auth.uid()) = id);

drop policy if exists "conversations_own_rows" on public.conversations;
create policy "conversations_read_own_rows" on public.conversations
    for select to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "conversation_turns_own_rows" on public.conversation_turns;
create policy "conversation_turns_read_own_rows" on public.conversation_turns
    for select to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "pending_actions_own_rows" on public.pending_actions;
create policy "pending_actions_read_own_rows" on public.pending_actions
    for select to authenticated
    using ((select auth.uid()) = user_id);
