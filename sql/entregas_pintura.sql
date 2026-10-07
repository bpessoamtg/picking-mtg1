-- =====================================================
-- ENTREGAS À PINTURA (um registo por entrega)
-- Correr uma vez no SQL Editor do Supabase (projeto mtg1-picking).
--
-- Até aqui cada linha de pintura guardava só o TOTAL entregue e a data da
-- ÚLTIMA alteração: 10 un. na segunda + 15 na terça ficavam "25, terça" e a
-- segunda desaparecia. Para a lista de entregas por dia (admin) cada entrega
-- passa a ficar registada à parte, com a quantidade dessa vez, a hora e quem.
-- =====================================================

create table if not exists entregas_pintura (
  id            uuid primary key default gen_random_uuid(),
  plan_id       text not null,
  plan_item_id  text not null references plan_items(id) on delete cascade,
  quantidade    integer not null,                 -- entregue nesta vez (negativo = correção para baixo)
  total_apos    integer not null,                 -- total entregue na linha depois desta entrega
  entregue_em   timestamptz not null default now(),
  entregue_por  text,
  origem        text not null default 'app'       -- 'app' ou 'historico' (ver abaixo)
);

alter table entregas_pintura enable row level security;
drop policy if exists "allow_all_entregas_pintura" on entregas_pintura;
create policy "allow_all_entregas_pintura" on entregas_pintura for all using (true) with check (true);

create index if not exists idx_entregas_pintura_em   on entregas_pintura(entregue_em);
create index if not exists idx_entregas_pintura_item on entregas_pintura(plan_item_id);

-- Histórico: das entregas anteriores só se sabe o total e a última data de cada
-- linha, por isso entram como uma entrega única nessa data. Nas entregas
-- parciais feitas em vários dias, a data fica a da última (a app assinala-as).
-- Pode correr-se outra vez sem duplicar nada.
insert into entregas_pintura (plan_id, plan_item_id, quantidade, total_apos, entregue_em, entregue_por, origem)
select pi.plan_id, pi.id, pi.qty_entregue, pi.qty_entregue, pi.entregue_em, pi.entregue_por, 'historico'
  from plan_items pi
  join plans p on p.id = pi.plan_id
 where p.tipo = 'pintura'
   and pi.qty_entregue > 0
   and pi.entregue_em is not null
   and not exists (select 1 from entregas_pintura e where e.plan_item_id = pi.id);
