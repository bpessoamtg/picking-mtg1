-- =====================================================
-- ENTREGAS À PINTURA REGISTADAS NOS EXCEL DA EXPEDIÇÃO (2026-11-05)
-- Correr uma vez no SQL Editor do Supabase (projeto mtg1-picking).
--
-- A app só conhece as entregas das linhas dos planos de pintura; as obras que
-- entram sem plano só ficam no Excel (Kanban das colunas, Pintura Kanban dos
-- braços). O script scripts/importar_entregas_excel.py copia-as para aqui às
-- 9h e às 16h, e a pesquisa por OV das Entregas mostra-as.
-- =====================================================

create table if not exists entregas_excel (
  id           bigserial primary key,
  grupo        text        not null check (grupo in ('colunas', 'acessorios')),
  ov           text        not null,
  modelo       text,
  quantidade   integer,
  data         date        not null,
  operador     text,
  importado_em timestamptz not null default now()
);
create index if not exists entregas_excel_ov on entregas_excel (ov);

alter table entregas_excel enable row level security;
drop policy if exists "ler entregas excel" on entregas_excel;
create policy "ler entregas excel" on entregas_excel for select using (true);
grant select on entregas_excel to anon;

-- Substitui as entregas de um Excel inteiro numa só gravação. Recusa uma
-- leitura muito mais pequena do que a que está gravada (ficheiro a meio de
-- sincronizar, separador errado), para nunca deixar a pesquisa vazia.
create or replace function public.importar_entregas_excel(p_grupo text, p_linhas jsonb)
returns json
language plpgsql
security definer
set search_path = public
as $$
declare
  v_atual integer;
  v_novo  integer := jsonb_array_length(coalesce(p_linhas, '[]'::jsonb));
begin
  if p_grupo not in ('colunas', 'acessorios') then
    raise exception 'grupo invalido';
  end if;
  select count(*) into v_atual from entregas_excel where grupo = p_grupo;
  if v_novo < v_atual * 0.9 then
    raise exception 'leitura com % linhas, menos do que as % gravadas: nada alterado', v_novo, v_atual;
  end if;
  delete from entregas_excel where grupo = p_grupo;
  insert into entregas_excel (grupo, ov, modelo, quantidade, data, operador)
  select p_grupo, l->>'ov', l->>'modelo', nullif(l->>'quantidade', '')::numeric::integer,
         (l->>'data')::date, l->>'operador'
    from jsonb_array_elements(p_linhas) l;
  return json_build_object('ok', true, 'grupo', p_grupo, 'antes', v_atual, 'agora', v_novo);
end;
$$;
revoke all on function public.importar_entregas_excel(text, jsonb) from public;
grant execute on function public.importar_entregas_excel(text, jsonb) to anon;
