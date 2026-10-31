-- Existing active duplicates must be resolved explicitly before applying this migration.
create unique index if not exists search_runs_active_query_unique
on public.search_runs (user_id, lower(btrim(query)))
where status in ('pending', 'processing');
alter table public.search_runs add column if not exists worker_failures integer not null default 0 check (worker_failures >= 0);
