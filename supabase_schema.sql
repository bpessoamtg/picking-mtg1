-- =====================================================
-- MTG1 Picking App — Supabase Schema
-- Correr no SQL Editor do Supabase Dashboard
-- =====================================================

-- TABELA: plans
create table if not exists plans (
  id              text primary key,
  tipo            text not null check (tipo in ('carga','pintura')),
  nome            text not null,
  data            date not null,
  hora_carregar   text,
  transportadora  text,
  status          text not null default 'em_separacao',
  grupo           text not null default 'ambos',
  criado_por      text,
  criado_em       timestamptz default now(),
  pdf_base64      text,
  pdf_name        text
);

-- TABELA: plan_items
create table if not exists plan_items (
  id              text primary key,
  plan_id         text not null references plans(id) on delete cascade,
  model           text,
  ref             text,
  desc_item       text,
  tipo_galva      text,
  ov              text,
  descarga        text,
  fiada           text,
  cesta           text,
  qty_pedida      integer default 0,
  qty_separada    integer default 0,
  separado        boolean default false,
  separado_por    text,
  separado_em     timestamptz,
  entregue        boolean default false,
  qty_entregue    integer default 0,
  entregue_em     timestamptz,
  entregue_nota   text
);

-- =====================================================
-- ROW LEVEL SECURITY
-- =====================================================
alter table plans      enable row level security;
alter table plan_items enable row level security;

create policy "allow_all_plans"      on plans      for all using (true) with check (true);
create policy "allow_all_plan_items" on plan_items for all using (true) with check (true);

-- =====================================================
-- ÍNDICES para performance
-- =====================================================
create index if not exists idx_plan_items_plan_id on plan_items(plan_id);
create index if not exists idx_plans_data         on plans(data desc);
create index if not exists idx_plans_tipo         on plans(tipo);
