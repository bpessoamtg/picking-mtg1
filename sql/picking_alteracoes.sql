-- =====================================================
-- LEITURA SÓ DO QUE MUDOU (2026-10-20)
-- Correr uma vez no SQL Editor do Supabase (projeto mtg1-picking).
--
-- A app lia todos os planos de sempre a cada 5 s (cerca de 170 KB por leitura,
-- 120 MB por hora por aparelho aberto) e a organização passou a quota de
-- tráfego do plano gratuito. Com isto, cada leitura de 5 s traz só os planos e
-- as linhas alterados desde a anterior, mais uma assinatura dos ids: se
-- aparecer ou desaparecer algum plano ou linha, a app faz uma leitura completa.
-- =====================================================

alter table plans      add column if not exists updated_at timestamptz not null default now();
alter table plan_items add column if not exists updated_at timestamptz not null default now();
create index if not exists plans_updated_at_idx      on plans (updated_at);
create index if not exists plan_items_updated_at_idx on plan_items (updated_at);

create or replace trigger plans_updated_at
  before update on plans
  for each row execute function public.update_updated_at_column();
create or replace trigger plan_items_updated_at
  before update on plan_items
  for each row execute function public.update_updated_at_column();

create or replace function public.picking_alteracoes(p_desde timestamptz)
returns json
language sql
stable
set search_path = public
as $$
  select json_build_object(
    'agora', now(),
    'assinatura', (select md5(coalesce(string_agg(id::text, ',' order by id), '')) from plans)
               || (select md5(coalesce(string_agg(id::text, ',' order by id), '')) from plan_items),
    'planos', coalesce((select json_agg(to_jsonb(p) - 'pdf_base64') from plans p where p.updated_at > p_desde), '[]'::json),
    'linhas', coalesce((select json_agg(i) from plan_items i where i.updated_at > p_desde), '[]'::json)
  );
$$;
grant execute on function public.picking_alteracoes(timestamptz) to anon;
