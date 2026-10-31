create extension if not exists pgcrypto;
create table public.saved_products (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 500),
  url text,
  description text,
  source text not null,
  created_at timestamptz not null default now()
);
create index saved_products_user_created_idx on public.saved_products (user_id, created_at desc);
alter table public.saved_products enable row level security;
create policy "Users read their own saved products" on public.saved_products for select to authenticated using (auth.uid() = user_id);
create policy "Users save their own products" on public.saved_products for insert to authenticated with check (auth.uid() = user_id);
create policy "Users delete their own saved products" on public.saved_products for delete to authenticated using (auth.uid() = user_id);
