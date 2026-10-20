-- =====================================================
-- BAIXA NO PARQUE QUE AGUENTA FALTA DE REDE (fase 3)
-- Correr uma vez no SQL Editor do Supabase (projeto mtg1-picking), depois do
-- supabase/parque_movimento.sql do parque (usa as funções parque_bloquear e
-- parque_ajustar de lá).
--
-- Substitui, na app de picking, a função picking_saida (que fica na base de
-- dados, sem uso, para as apps ainda abertas com a versão antiga).
--
-- O que muda em relação à picking_saida:
--  1. Cada baixa traz um número único (pedido_id). Se chegar duas vezes -- a
--     resposta perdeu-se na rede e o tablet reenviou --, a segunda devolve o
--     resultado da primeira e não desconta outra vez.
--  2. A contagem do operador ("ficam X na cesta") vem com a hora em que foi
--     feita. Se ninguém mexeu na cesta desde essa hora, aplica-se como hoje
--     (a cesta fica com X e o admin é avisado da correção). Se mexeram depois,
--     aplicá-la apagava esse movimento: desconta-se só o que foi tirado e o
--     admin recebe uma mensagem para confirmar.
--  4. (2026-10-20) Várias linhas do mesmo modelo na mesma cesta e fiada são
--     paletes: a baixa conta com o total de todas (antes usava uma ao acaso e
--     podia dizer "insuficiente" com material que chegava). E fica na fila
--     das gravações do parque, para não se cruzar com um movimento feito ao
--     mesmo tempo na app do parque.
--  3. Sem stock suficiente, a baixa não falha em silêncio (o operador já não
--     está a olhar quando o tablet volta à rede): não mexe na cesta e avisa o
--     admin.
-- =====================================================

-- Pedidos já processados (só a função lê e escreve: sem políticas para anon)
create table if not exists picking_baixa_pedidos (
  pedido_id  uuid primary key,
  resultado  json not null,
  criado_em  timestamptz not null default now()
);
alter table picking_baixa_pedidos enable row level security;

-- A hora da última alteração de cada cesta é o que diz se alguém mexeu nela
-- depois da contagem. O gatilho já vinha do Lovable; garante-se que existe.
create or replace function public.update_updated_at_column()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
create or replace trigger update_stock_items_updated_at
  before update on stock_items
  for each row execute function public.update_updated_at_column();

create or replace function public.picking_baixa(
  p_pedido_id        uuid,
  p_modelo           text,
  p_cesta            text,
  p_fiada            text,
  p_quantidade       integer,
  p_utilizador       text,
  p_sobra_confirmada integer     default null,   -- o que o operador diz que ficou (null = não contou)
  p_contado_em       timestamptz default null,   -- quando o operador tirou o material
  p_sem_rede         boolean     default false,  -- confirmado no tablet sem rede
  p_notas            text        default null
) returns json
language plpgsql
security definer
set search_path = public
as $$
declare
  v_res       json;
  v_cod_sap   text;
  v_atual     integer;
  v_alterado  timestamptz;
  v_esperado  integer;
  v_final     integer;
  v_mov_id    uuid;
  v_estado    text;
  v_mexida    boolean;
  v_descontou boolean := false;
  v_msg       text;
  v_quem      text := coalesce(nullif(btrim(p_utilizador), ''), 'app-picking');
  v_quando    timestamptz := least(coalesce(p_contado_em, now()), now());   -- relógio do tablet adiantado conta como agora
  v_hora      text;
  v_notas     text;
begin
  if p_pedido_id is null then
    raise exception 'pedido_id obrigatorio';
  end if;
  if coalesce(btrim(p_modelo), '') = '' or coalesce(btrim(p_cesta), '') = '' or coalesce(btrim(p_fiada), '') = '' then
    raise exception 'modelo, cesta e fiada sao obrigatorios';
  end if;
  if p_quantidade is null or p_quantidade <= 0 then
    raise exception 'quantidade tem de ser um inteiro maior que zero';
  end if;
  if p_sobra_confirmada is not null and p_sobra_confirmada < 0 then
    raise exception 'sobra_confirmada nao pode ser negativa';
  end if;

  -- O mesmo pedido outra vez: devolve o resultado da primeira vez. O insert
  -- primeiro (e não um select) faz com que dois pedidos iguais em simultâneo
  -- esperem um pelo outro em vez de descontarem os dois.
  insert into picking_baixa_pedidos (pedido_id, resultado)
  values (p_pedido_id, '{"ok": true, "estado": "em_curso"}')
  on conflict (pedido_id) do nothing;
  if not found then
    select resultado into v_res from picking_baixa_pedidos where pedido_id = p_pedido_id;
    return v_res;
  end if;

  v_hora  := to_char(v_quando at time zone 'Europe/Lisbon', 'HH24:MI');
  v_notas := coalesce(nullif(btrim(p_notas), ''), 'app de picking')
             || case when p_sem_rede then ' (sem rede, ' || v_hora || ')' else '' end;

  select cod_sap into v_cod_sap from model_sap_lookup where modelo = p_modelo;

  v_atual := parque_bloquear(p_modelo, p_cesta, p_fiada);
  select max(updated_at) into v_alterado
    from stock_items
   where modelo = p_modelo and cesta = p_cesta and fiada = p_fiada;
  v_esperado := v_atual - p_quantidade;

  -- O operador contou o que ficou na cesta? A contagem é de uma hora concreta:
  -- só se pode comparar com o sistema se ninguém mexeu na cesta depois dela
  -- (senão uma entrada posterior podia coincidir por acaso e esconder o erro).
  if p_sobra_confirmada is not null then
    select exists (
             select 1 from movements m
              where m.modelo = p_modelo
                and m.created_at > v_quando
                and ((m.cesta_origem = p_cesta and m.fiada_origem = p_fiada)
                  or (m.cesta_destino = p_cesta and m.fiada_destino = p_fiada)))
           or (v_alterado is not null and v_alterado > v_quando)
      into v_mexida;
  end if;

  if p_sobra_confirmada is null or (not v_mexida and p_sobra_confirmada = v_esperado) then
    -- Baixa simples: o operador não contou, ou contou e bate certo
    if v_atual < p_quantidade then
      v_estado := 'insuficiente';
      v_final  := v_atual;
    else
      v_estado := 'normal';
      v_final  := v_esperado;
      perform parque_ajustar(p_modelo, v_cod_sap, p_cesta, p_fiada, -p_quantidade);
      v_descontou := true;
    end if;
  elsif not v_mexida then
    -- Ninguém mexeu desde a contagem: a contagem é a verdade, como com rede
    v_estado := 'corrigido';
    v_final  := p_sobra_confirmada;
    perform parque_ajustar(p_modelo, v_cod_sap, p_cesta, p_fiada, v_final - v_atual);
    v_descontou := true;
  else
    -- Mexeram depois da contagem: pôr a cesta em X apagava esse movimento.
    -- Desconta-se só o que foi tirado e o admin confirma.
    v_estado := 'verificar';
    if v_atual >= p_quantidade then
      v_final := v_esperado;
      perform parque_ajustar(p_modelo, v_cod_sap, p_cesta, p_fiada, -p_quantidade);
      v_descontou := true;
    else
      v_final := v_atual;
    end if;
  end if;

  -- Movimento no histórico do parque (não há quando a cesta ficou como estava)
  if v_descontou then
    insert into movements (tipo, modelo, cod_sap, cesta_origem, fiada_origem,
                           cesta_destino, fiada_destino, quantidade, utilizador, notas)
    values ('saida', p_modelo, v_cod_sap, p_cesta, p_fiada,
            p_cesta, p_fiada, p_quantidade, v_quem, v_notas)
    returning id into v_mov_id;
  end if;

  -- Mensagem ao admin
  if v_estado = 'corrigido' then
    v_msg := format('Stock corrigido por %s: %s em %s/%s. Sistema: %s un. → Corrigido: %s un. (saida) — via app de picking da expedição%s',
                    v_quem, p_modelo, p_cesta, p_fiada, v_esperado, v_final,
                    case when p_sem_rede then ' (contado sem rede às ' || v_hora || ')' else '' end);
  elsif v_estado = 'verificar' and not v_descontou then
    v_msg := format('Verificar %s em %s/%s: %s contou %s un. às %s%s, mas depois disso houve movimentos nesta cesta, por isso a contagem não foi aplicada. A baixa das %s un. retiradas também não foi feita: o sistema só tem %s un. — via app de picking da expedição',
                    p_modelo, p_cesta, p_fiada, v_quem, p_sobra_confirmada, v_hora,
                    case when p_sem_rede then ' (sem rede)' else '' end, p_quantidade, v_atual);
  elsif v_estado = 'verificar' then
    v_msg := format('Verificar %s em %s/%s: %s contou %s un. às %s%s, mas depois disso houve movimentos nesta cesta, por isso a contagem não foi aplicada. Foram descontadas as %s un. retiradas; o sistema tem agora %s un. — via app de picking da expedição',
                    p_modelo, p_cesta, p_fiada, v_quem, p_sobra_confirmada, v_hora,
                    case when p_sem_rede then ' (sem rede)' else '' end, p_quantidade, v_final);
  elsif v_estado = 'insuficiente' then
    v_msg := format('Verificar %s em %s/%s: %s retirou %s un. às %s%s, mas o sistema só tinha %s un. A baixa não foi feita. — via app de picking da expedição',
                    p_modelo, p_cesta, p_fiada, v_quem, p_quantidade, v_hora,
                    case when p_sem_rede then ' (sem rede)' else '' end, v_atual);
  end if;
  if v_msg is not null then
    insert into admin_notifications (message, movimento_id, utilizador)
    values (v_msg, v_mov_id, v_quem);
  end if;

  v_res := json_build_object('ok', true, 'estado', v_estado, 'sobra_final', v_final, 'movimento_id', v_mov_id);
  update picking_baixa_pedidos set resultado = v_res where pedido_id = p_pedido_id;
  return v_res;
end;
$$;

revoke all on function public.picking_baixa(uuid,text,text,text,integer,text,integer,timestamptz,boolean,text) from public;
grant execute on function public.picking_baixa(uuid,text,text,text,integer,text,integer,timestamptz,boolean,text) to anon;
