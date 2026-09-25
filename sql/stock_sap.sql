-- =====================================================
-- STOCK SAP (extração ZMB52)
-- Correr uma vez no SQL Editor do Supabase (projeto mtg1-picking).
--
-- Guarda a última extração do SAP (ZMB52, materiais CI* + *_V*, centro MT01,
-- depósito 01) para o operador ver, na linha do plano, quanto stock existe
-- desse material. É só leitura para a app: quem separa não altera nada aqui.
-- O import (admin) substitui a lista inteira de cada vez.
-- =====================================================

create table if not exists stock_sap (
  ref             text primary key,          -- código SAP do material (= plan_items.ref)
  descricao       text,                      -- "Texto breve material"
  quantidade      numeric not null default 0,-- "Utilização livre", somada por material
  atualizado_em   timestamptz not null default now(),
  atualizado_por  text
);

alter table stock_sap enable row level security;

drop policy if exists "allow_all_stock_sap" on stock_sap;
create policy "allow_all_stock_sap" on stock_sap for all using (true) with check (true);

create index if not exists idx_stock_sap_atualizado on stock_sap(atualizado_em);
