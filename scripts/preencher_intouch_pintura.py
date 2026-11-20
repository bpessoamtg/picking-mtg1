"""Grava nas linhas de pintura o que já foi fechado no inTouch.

Os empilhadoristas registam cada entrega à pintura na app e voltam a
registá-la no plano de pintura do inTouch. A app compara as duas e mostra
"Fechado no inTouch" ou "Falta fechar no inTouch" (comparação feita na app,
em tempo real, contra a quantidade entregue na app).

Dois passos, porque o inTouch só se lê pela consulta guardada:
  1) correr a consulta guardada entregas_pintura_intouch (CPIS) com
     data_inicio = hoje - 45 dias (exportar json)
  2) python preencher_intouch_pintura.py <export_intouch.json> [<export_sap.json>] [--aplicar]
     o segundo ficheiro é o export da consulta linhas_ov_mt01 (o mesmo do
     passo dos códigos SAP); serve para ligar linhas com descrição genérica
     ("Door", "Lighting Mast") pelo número da linha da OV.
     Sem --aplicar só mostra o que faria.

Regras:
- No inTouch a mesma linha da OV aparece num dia por cada entrega parcial e,
  às vezes, repetida quando o plano passa para outro dia. Soma-se por linha da
  OV, limitado à quantidade dessa linha.
- Se a mesma linha da OV está em várias linhas da app (planos de dias
  diferentes), o fechado no inTouch reparte-se por elas, do plano mais antigo
  para o mais recente.
- Se a app tem entregue, nas linhas ligadas à mesma linha da OV, mais do que
  a quantidade dessa linha (a mesma linha em dois planos, entregue nos dois),
  o excesso é entrega repetida: conta como fechado, nunca como "falta fechar".
- Linha da app que não se consegue ligar a nenhuma linha da OV fica com -1
  (a app não mostra nada; nunca "falta fechar" por falta de ligação).
  Linha ainda não lida (vazio) conta na app como 0 fechado, para o aviso
  aparecer logo a seguir à entrega, antes da próxima leitura do inTouch.
"""
import argparse
import datetime
import json
import re
import sys
import urllib.parse

sys.path.insert(0, __file__.rsplit('\\', 1)[0].rsplit('/', 1)[0])
from preencher_ref_pintura import pedido, NAO_PECA  # noqa: E402

DIAS_PLANOS = 21


def ler(path):
    d = json.load(open(path, encoding='utf-8'))
    cols = [c['nome'] if isinstance(c, dict) else c for c in d['colunas']]
    return [dict(zip(cols, r)) for r in d['linhas']]


def sem_v(m):
    m = (m or '').strip().upper()
    return m[:-2] if m.endswith('_V') else m


def ultima(txt):
    w = (txt or '').strip().split()
    return w[-1].upper() if w else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('intouch', nargs='?')
    ap.add_argument('--listar-ovs', action='store_true', help='OVs das linhas entregues (para a consulta linhas_ov_mt01)')
    ap.add_argument('sap', nargs='?')
    ap.add_argument('--aplicar', action='store_true')
    a = ap.parse_args()

    if a.listar_ovs:
        desde = (datetime.date.today() - datetime.timedelta(days=DIAS_PLANOS)).isoformat()
        planos = pedido('GET', '/plans?tipo=eq.pintura&data=gte.' + desde + '&select=plan_items(ov,qty_entregue)')
        ovs = sorted({(i.get('ov') or '').strip().lstrip('0').zfill(10) for p in planos for i in p['plan_items']
                      if (i.get('ov') or '').strip().isdigit() and (i.get('qty_entregue') or 0) > 0})
        print(json.dumps(ovs))
        return
    if not a.intouch:
        sys.exit('Falta o ficheiro exportado da consulta entregas_pintura_intouch (ou --listar-ovs).')

    # inTouch: por OV + linha, soma limitada à quantidade da linha
    it_item = {}
    it_desc = {}
    for r in ler(a.intouch):
        ov = str(r['ov']).lstrip('0'); item = str(r['item']).lstrip('0')
        k = (ov, item)
        q = float(r['qtd_entregue'] or 0)
        cap = float(r['qtd_plano'] or 0) or None
        s, c = it_item.get(k, (0.0, cap))
        it_item[k] = (s + q, cap or c)
        it_desc.setdefault(k, ultima(r['descricao']))
    fechado = {k: (min(s, c) if c else s) for k, (s, c) in it_item.items()}
    ovs_intouch = {k[0] for k in fechado}

    # SAP: OV + material/texto -> linhas da OV
    sap = {}
    sap_qtd = {}
    if a.sap:
        for r in ler(a.sap):
            mat = str(r['MATERIAL']).strip().upper()
            if NAO_PECA.match(mat):
                continue
            sap.setdefault(str(r['OV']).lstrip('0'), []).append(
                (str(r['ITEM']).lstrip('0'), mat, ultima(r['TEXTO']), str(r['TEXTO'] or '').strip().upper()))
            sap_qtd[(str(r['OV']).lstrip('0'), str(r['ITEM']).lstrip('0'))] = float(r['QUANTIDADE'] or 0)

    def itens_da_linha(ov, modelo, ref):
        m = sem_v(modelo); refu = (ref or '').strip().upper()
        cand = {k[1] for k, d in it_desc.items() if k[0] == ov and d and sem_v(d) == m}
        for item, mat, ult, txt in sap.get(ov, []):
            if (refu and mat == refu) or sem_v(mat) == m or sem_v(ult) == m or txt == m:
                cand.add(item)
        return frozenset(cand)

    desde = (datetime.date.today() - datetime.timedelta(days=DIAS_PLANOS)).isoformat()
    try:
        planos = pedido('GET', '/plans?tipo=eq.pintura&data=gte.' + desde
                        + '&select=id,nome,data,plan_items(id,ov,model,ref,qty_entregue,intouch_qtd)')
        tem_campo = True
    except Exception:
        # campos ainda nao criados no Supabase: so ensaio
        planos = pedido('GET', '/plans?tipo=eq.pintura&data=gte.' + desde
                        + '&select=id,nome,data,plan_items(id,ov,model,ref,qty_entregue)')
        tem_campo = False
        if a.aplicar:
            print('Campos intouch_qtd/intouch_em ainda nao existem: corrido em ensaio.')
            a.aplicar = False
    linhas = []
    for p in planos:
        for i in p['plan_items']:
            ov = (i.get('ov') or '').strip().lstrip('0')
            if not ov.isdigit() or not (i.get('qty_entregue') or 0) > 0:
                continue
            linhas.append(dict(i, ov=ov, data=p['data'], plano=p['nome']))

    grupos = {}
    sem_ligacao = []
    for l in linhas:
        itens = itens_da_linha(l['ov'], l['model'], l.get('ref'))
        if not itens:
            # OV inteira sem nada no inTouch = ainda nada fechado; senão não se sabe qual linha
            if l['ov'] not in ovs_intouch and sap.get(l['ov']):
                grupos.setdefault((l['ov'], frozenset()), []).append(l)
            else:
                sem_ligacao.append(l)
            continue
        grupos.setdefault((l['ov'], itens), []).append(l)

    novos = {}
    repetidas = 0
    for (ov, itens), ls in grupos.items():
        resto = sum(fechado.get((ov, it), 0) for it in itens)
        # quantidade total das linhas da OV (só se o inTouch as tem todas)
        # (a do inTouch; se a linha ainda não está no inTouch, a do SAP)
        caps = [(it_item[(ov, it)][1] if (ov, it) in it_item else None) or sap_qtd.get((ov, it)) for it in itens]
        devido = sum(caps) if itens and all(caps) else None
        ls.sort(key=lambda x: (x['data'], x['id']))
        for n, l in enumerate(ls):
            q = l['qty_entregue']
            if devido is None:
                precisa, excesso = q, 0
            else:
                precisa = min(q, devido)
                excesso = q - precisa
                devido -= precisa
            v = resto if n == len(ls) - 1 else min(resto, precisa)
            resto -= v
            if excesso:
                repetidas += 1
            novos[l['id']] = int(round(v + excesso))
    for l in sem_ligacao:
        novos[l['id']] = -1

    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    mudou = {i: v for i, v in novos.items()
             if next(l for l in linhas if l['id'] == i).get('intouch_qtd') != v}
    if a.aplicar:
        for i, v in mudou.items():
            pedido('PATCH', '/plan_items?id=eq.' + urllib.parse.quote(str(i)), {'intouch_qtd': v, 'intouch_em': agora})

    por_id = {l['id']: l for l in linhas}
    falta = [(por_id[i], v) for i, v in novos.items() if 0 <= v < por_id[i]['qty_entregue']]
    ligadas = sum(1 for v in novos.values() if v >= 0)
    acao = 'gravadas' if a.aplicar else 'a gravar (ensaio, usar --aplicar)'
    print(f'Fechado no inTouch (pintura): {ligadas} linhas entregues ligadas, '
          f'{ligadas - len(falta)} fechadas, {len(falta)} com falta de fechar, '
          f'{len(sem_ligacao)} sem ligação; {len(mudou)} {acao}'
          + (f'; {repetidas} com entrega repetida em dois planos (não contam)' if repetidas else ''))
    if not a.aplicar:
        for l, v in falta[:25]:
            print(f'  falta: {l["data"]} {l["plano"][:28]} OV {l["ov"]} {l["model"]} app {l["qty_entregue"]} inTouch {v}')
        for l in sem_ligacao[:10]:
            print(f'  sem ligação: OV {l["ov"]} {l["model"]}')


if __name__ == '__main__':
    main()
