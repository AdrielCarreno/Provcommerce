import { createBrowserClient } from '@supabase/ssr';
export function supabase(){const url=process.env.NEXT_PUBLIC_SUPABASE_URL, key=process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;if(!url||!key) throw new Error('Configura las variables públicas de Supabase.');return createBrowserClient(url,key)}
