-- Baixa de stock no parque, pedida pela app de picking da expedição.
-- Replica a lógica de "saida" do MovementTab da app de acessórios:
-- desconta da cesta, apaga a linha quando sobra zero, regista o movimento
-- no histórico e, se o operador corrigir a sobra, avisa o administrador.
--
-- SECURITY DEFINER: corre com privilégios do dono, para poder escrever nas
-- tabelas do parque sem abrir essas tabelas ao papel anon.
create or replace function public.picking_saida(
  p_modelo           text,
  p_cesta            text,
  p_fiada            text,
  p_quantidade       integer,
  p_utilizador       text,
  p_sobra_confirmada integer default null,
  p_notas            text default null
) returns json
language plpgsql
security definer
set search_path = public
as $$
declare
  v_cod_sap    text;
  v_id         uuid;
  v_atual      integer;
  v_esperado   integer;
  v_sobra      integer;
  v_mov_id     uuid;
  v_quem       text := coalesce(nullif(btrim(p_utilizador), ''), 'app-picking');
begin
  if coalesce(btrim(p_modelo), '') = ''
     or coalesce(btrim(p_cesta), '') = ''
     or coalesce(btrim(p_fiada), '') = '' then
    raise exception 'modelo, cesta e fiada sao obrigatorios';
  end if;
  if p_quantidade is null or p_quantidade <= 0 then
    raise exception 'quantidade tem de ser um inteiro maior que zero';
  end if;
  if p_sobra_confirmada is not null and p_sobra_confirmada < 0 then
    raise exception 'sobra_confirmada nao pode ser negativa';
  end if;

  select cod_sap into v_cod_sap
    from model_sap_lookup where modelo = p_modelo;

  select id, quantidade into v_id, v_atual
    from stock_items
   where modelo = p_modelo and cesta = p_cesta and fiada = p_fiada
   limit 1;

  v_atual    := coalesce(v_atual, 0);
  v_esperado := v_atual - p_quantidade;

  if p_sobra_confirmada is null then
    -- Caso normal: tem de haver stock suficiente
    if v_id is null or v_atual < p_quantidade then
      return json_build_object('ok', false, 'erro', 'stock insuficiente',
                               'quantidade_atual', v_atual);
    end if;
    v_sobra := v_esperado;
    if v_sobra = 0 then
      delete from stock_items where id = v_id;
    else
      update stock_items set quantidade = v_sobra where id = v_id;
    end if;
  else
    -- Correção: o operador diz quanto ficou mesmo na cesta
    v_sobra := p_sobra_confirmada;
    if v_id is not null then
      if v_sobra = 0 then
        delete from stock_items where id = v_id;
      else
        update stock_items set quantidade = v_sobra where id = v_id;
      end if;
    elsif v_sobra > 0 then
      insert into stock_items (modelo, cod_sap, cesta, fiada, quantidade)
      values (p_modelo, v_cod_sap, p_cesta, p_fiada, v_sobra);
    end if;
  end if;

  insert into movements (tipo, modelo, cod_sap, cesta_origem, fiada_origem,
                         cesta_destino, fiada_destino, quantidade, utilizador, notas)
  values ('saida', p_modelo, v_cod_sap, p_cesta, p_fiada,
          p_cesta, p_fiada, p_quantidade, v_quem, p_notas)
  returning id into v_mov_id;

  if p_sobra_confirmada is not null then
    insert into admin_notifications (message, movimento_id, utilizador)
    values (
      format('Stock corrigido por %s: %s em %s/%s. Sistema: %s un. → Corrigido: %s un. (saida) — via app de picking da expedição',
             v_quem, p_modelo, p_cesta, p_fiada, v_esperado, v_sobra),
      v_mov_id, v_quem);
  end if;

  return json_build_object('ok', true, 'sobra_final', v_sobra, 'movimento_id', v_mov_id);
end;
$$;

revoke all on function public.picking_saida(text,text,text,integer,text,integer,text) from public;
grant execute on function public.picking_saida(text,text,text,integer,text,integer,text) to anon;
