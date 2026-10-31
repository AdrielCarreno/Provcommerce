create table public.search_runs (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 query text not null check (char_length(query) between 2 and 200),
 status text not null check (status in ('pending','processing','completed','failed')),
 actor_run_id text, error text,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (id, user_id)
);
create function public.touch_search_run() returns trigger language plpgsql set search_path = '' as $$ begin new.updated_at = now(); return new; end; $$;
create trigger search_run_updated before update on public.search_runs for each row execute function public.touch_search_run();
create table public.search_results (
 id uuid primary key default gen_random_uuid(),
 search_id uuid not null, user_id uuid not null,
 title text not null, url text not null, description text, source text not null,
 supplier text, price numeric, currency text, minimum_order text,
 created_at timestamptz not null default now(),
 foreign key (search_id,user_id) references public.search_runs(id,user_id) on delete cascade,
 unique (search_id,url)
);
create index search_runs_user_created_idx on public.search_runs(user_id, created_at desc);
create index search_results_user_search_idx on public.search_results(user_id, search_id);
alter table public.search_runs enable row level security;
alter table public.search_results enable row level security;
create policy "Users read own searches" on public.search_runs for select to authenticated using (user_id = auth.uid());
create policy "Users read own search results" on public.search_results for select to authenticated using (user_id = auth.uid());
