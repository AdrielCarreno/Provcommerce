-- Resolve any users with more than one active run before applying this migration.
-- The unique index enforces the limit atomically across API instances.
create unique index if not exists search_runs_one_active_per_user
on public.search_runs (user_id) where status in ('pending', 'processing');
