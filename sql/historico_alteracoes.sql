-- =====================================================
-- CÓPIA DO QUE SE APAGA (auditoria 2026-10-20)
-- Correr uma vez no SQL Editor do Supabase (projeto mtg1-picking).
--
-- As tabelas do picking aceitam apagar com a chave pública da app, e o plano
-- gratuito do Supabase não tem cópias de segurança: um engano (ou alguém de
-- fora) apagava planos, linhas e entregas sem forma de os recuperar.
-- Daqui para a frente, cada linha apagada fica copiada numa tabela à parte,
-- que a chave pública não consegue ler nem apagar. Para recuperar, pede-se ao
-- Claude (ou lê-se no Table Editor).
-- =====================================================

create table if not exists historico_alteracoes (
  id        bigserial primary key,
  tabela    text        not null,
  operacao  text        not null,
  linha     jsonb       not null,
  quando    timestamptz not null default now()
);
create index if not exists historico_alteracoes_quando on historico_alteracoes (quando);
alter table historico_alteracoes enable row level security;
revoke all on historico_alteracoes from anon, authenticated;

create or replace function public.guardar_linha_apagada()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into historico_alteracoes (tabela, operacao, linha)
  values (tg_table_name, tg_op, to_jsonb(old));
  return old;
end;
$$;
revoke all on function public.guardar_linha_apagada() from public, anon, authenticated;

-- Os PDFs dos planos são grandes e o email original continua no Outlook:
-- guarda-se o plano sem o PDF
create or replace function public.guardar_plano_apagado()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into historico_alteracoes (tabela, operacao, linha)
  values (tg_table_name, tg_op, to_jsonb(old) - 'pdf_base64');
  return old;
end;
$$;
revoke all on function public.guardar_plano_apagado() from public, anon, authenticated;

create or replace trigger guardar_apagados after delete on plans
  for each row execute function public.guardar_plano_apagado();
create or replace trigger guardar_apagados after delete on plan_items
  for each row execute function public.guardar_linha_apagada();
create or replace trigger guardar_apagados after delete on entregas_pintura
  for each row execute function public.guardar_linha_apagada();
create or replace trigger guardar_apagados after delete on stock_items
  for each row execute function public.guardar_linha_apagada();
