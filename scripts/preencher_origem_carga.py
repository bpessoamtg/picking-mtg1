"""Grava em cada linha dos planos de carga se o material sai de stock ou de
produção, e, nas colunas a produzir, quanto já passou na linha.

- Stock ou produção: é a "Utilização" da linha da OV no SAP (Stock, Produzir,
  Stock para Pintura, ...), a mesma que se vê no VA03.
- Já produzido: folha "Resumo" do Expedição_Colunas_2026.xlsm (QT Produzida e
  Quantidade por OV e material), que vem dos registos dos turnos. Não se usam
  as entradas do SAP porque a balança pode forçar entradas ao adiantar guias.
  Só se aplica às colunas (CG e CP) com utilização "Produzir".

Passos, porque o SAP só se lê pela consulta guardada:
  1) python preencher_origem_carga.py --listar-ovs
     imprime a lista JSON das OVs dos planos de carga de hoje em diante
  2) correr a consulta guardada linhas_ov_mt01 com essa lista (exportar json)
  3) python preencher_origem_carga.py <export.json> [--aplicar]
     sem --aplicar só mostra o que faria

Só grava as linhas em que alguma coisa mudou.
"""
import argparse
import collections
import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SUPABASE_URL = 'https://cpoghfbbawubcmdtmpfj.supabase.co'
ANON_KEY = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwb2do'
            'ZmJiYXd1YmNtZHRtcGZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA0MDUzMDYsImV4cCI6MjA5'
            'NTk4MTMwNn0.fdInpb2SViVNmSg7VR0cYDK6qkGROfFm5OWGTBi8ORA')
EXCEL = os.path.join(os.path.expanduser('~'), 'OneDrive - METALOGALVA - IRMÃOS SILVAS, S.A',
                     'Ficheiros de David Ribeiro - DL', 'Expedição', 'Colunas', 'Expedição_Colunas_2026.xlsm')
COLUNAS = ('CG', 'CP')
COLUNAS_NA_BASE = True
# Passam na linha mas não se registam no Excel das colunas: o Resumo diria
# sempre "falta produzir". Ficam só com a utilização (Bruno, 2026-11-11).
SEM_REGISTO_NO_EXCEL = {'CIPOR000G'}


def pedido(metodo, caminho, corpo=None):
    h = {'apikey': ANON_KEY, 'Authorization': 'Bearer ' + ANON_KEY, 'Content-Type': 'application/json'}
    if metodo == 'PATCH':
        h['Prefer'] = 'return=minimal'
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(SUPABASE_URL + '/rest/v1' + caminho, data=dados, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=60) as r:
        txt = r.read().decode('utf-8')
        return json.loads(txt) if txt else None


def linhas_dos_planos(dias_atras):
    desde = (datetime.date.today() - datetime.timedelta(days=dias_atras)).isoformat()
    base = '/plans?tipo=eq.carga&data=gte.' + desde + '&select=nome,data,plan_items(id,ov,ref,model,qty_pedida,tipo_galva'
    global COLUNAS_NA_BASE
    try:
        planos = pedido('GET', base + ',origem,prod_feitas,prod_total)')
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        COLUNAS_NA_BASE = False   # falta correr o SQL que cria as colunas: só ensaio
        planos = pedido('GET', base + ')')
    out = []
    for p in planos:
        for i in p['plan_items']:
            ov = (i.get('ov') or '').strip()
            if ov.isdigit():
                i['ov'] = ov.lstrip('0')
                i['plano'] = p['nome']
                out.append(i)
    return out


def txt(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return '' if v is None else str(v).strip()


def num(v):
    return v if isinstance(v, (int, float)) else 0


def ler_resumo():
    """(OV, material) -> [quantidade, produzidas] somadas, da folha Resumo."""
    import openpyxl
    import warnings
    warnings.simplefilter('ignore')
    tmp = os.path.join(tempfile.mkdtemp(), 'copia.xlsm')
    for tentativa in range(6):    # o Excel pode estar aberto ou a sincronizar: lê-se uma cópia
        try:
            shutil.copy2(EXCEL, tmp)
            break
        except PermissionError:
            if tentativa == 5:
                raise
            time.sleep(5)
    wb = openpyxl.load_workbook(tmp, read_only=True, data_only=True)
    it = wb['Resumo'].iter_rows(values_only=True)
    cab = [txt(c) for c in next(it)]
    iov, imat, iq, ip = cab.index('OV'), cab.index('CI'), cab.index('Quantidade'), cab.index('QT Produzida')
    res = collections.defaultdict(lambda: [0, 0])
    for r in it:
        if len(r) <= max(iov, imat, iq, ip) or r[iov] is None:
            continue
        k = (txt(r[iov]).lstrip('0'), txt(r[imat]).upper())
        res[k][0] += num(r[iq])
        res[k][1] += num(r[ip])
    wb.close()
    shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
    return res


def utilizacao_da_linha(linha, itens_ov):
    """A linha do plano não traz o item da OV: liga-se pelo material e, se o
    mesmo material tiver utilizações diferentes na OV, pela quantidade."""
    ref = (linha.get('ref') or '').strip().upper()
    cand = [x for x in itens_ov if x['mat'] == ref]
    if not cand:
        return None
    usos = {x['uso'] for x in cand}
    if len(usos) == 1:
        return usos.pop() or None
    q = linha.get('qty_pedida') or 0
    for filtro in (lambda x: x['qtd'] == q, lambda x: x['qtd'] >= q):
        usos = {x['uso'] for x in cand if filtro(x)}
        if len(usos) == 1:
            return usos.pop() or None
    return ' / '.join(sorted(u for u in {x['uso'] for x in cand} if u))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('export', nargs='?')
    ap.add_argument('--listar-ovs', action='store_true')
    ap.add_argument('--aplicar', action='store_true')
    ap.add_argument('--dias-atras', type=int, default=1, help='inclui planos com data até N dias atrás')
    a = ap.parse_args()

    linhas = linhas_dos_planos(a.dias_atras)
    if a.listar_ovs:
        print(json.dumps(sorted({l['ov'].zfill(10) for l in linhas})))
        return
    if not a.export:
        sys.exit('Falta o ficheiro exportado da consulta linhas_ov_mt01 (ou --listar-ovs).')

    d = json.load(open(a.export, encoding='utf-8'))
    cols = [c['nome'] for c in d['colunas']]
    if 'UTILIZACAO' not in cols:
        sys.exit('O ficheiro exportado não tem a utilização: correr de novo a consulta linhas_ov_mt01.')
    c = {n: cols.index(n) for n in ('OV', 'MATERIAL', 'QUANTIDADE', 'UTILIZACAO')}
    por_ov = collections.defaultdict(list)
    for r in d['linhas']:
        por_ov[str(r[c['OV']]).lstrip('0')].append({
            'mat': str(r[c['MATERIAL']]).strip().upper(), 'qtd': float(r[c['QUANTIDADE']] or 0),
            'uso': str(r[c['UTILIZACAO']] or '').strip()})

    try:
        resumo = ler_resumo()
        aviso_excel = ''
    except Exception as e:   # sem Excel grava-se a utilização na mesma
        resumo = None
        aviso_excel = f' (Excel das colunas NÃO lido: {e})'

    mudancas, conta = [], collections.Counter()
    for l in linhas:
        uso = utilizacao_da_linha(l, por_ov.get(l['ov'], []))
        novo = {'origem': uso, 'prod_feitas': None, 'prod_total': None}
        if uso is None:
            conta['sem utilização no SAP'] += 1
        elif (uso.startswith('Produzir') and l.get('tipo_galva') in COLUNAS
              and (l.get('ref') or '').strip().upper() not in SEM_REGISTO_NO_EXCEL):
            if resumo is None:
                novo['prod_feitas'], novo['prod_total'] = l.get('prod_feitas'), l.get('prod_total')
                conta['Produzir (sem Excel)'] += 1
            else:
                r = resumo.get((l['ov'], (l.get('ref') or '').strip().upper()))
                if r and r[0] > 0:
                    novo['prod_total'], novo['prod_feitas'] = int(r[0]), int(r[1])
                    conta['Produzir, já produzido' if r[1] >= r[0] else
                          ('Produzir, parcial' if r[1] > 0 else 'Produzir, falta produzir')] += 1
                else:
                    novo['prod_feitas'] = 0
                    conta['Produzir, sem produção registada'] += 1
        else:
            conta[uso] += 1
        if any(l.get(k) != v for k, v in novo.items()):
            mudancas.append((l, novo))

    if a.aplicar and not COLUNAS_NA_BASE:
        sys.exit('As colunas origem/prod_feitas/prod_total ainda não existem na base de dados: nada gravado.')
    if a.aplicar:
        agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for l, novo in mudancas:
            pedido('PATCH', '/plan_items?id=eq.' + urllib.parse.quote(str(l['id'])), dict(novo, origem_em=agora))

    acao = 'atualizadas' if a.aplicar else 'a atualizar (ensaio, usar --aplicar)'
    resumo_txt = ', '.join(f'{n} {k}' for k, n in conta.most_common())
    print(f'Stock/produção nas cargas: {len(mudancas)} linhas {acao} de {len(linhas)} -- {resumo_txt}{aviso_excel}')
    if not a.aplicar:
        for l, novo in mudancas:
            p = '' if novo['prod_feitas'] is None else f" · produzido {novo['prod_feitas']} de {novo['prod_total'] if novo['prod_total'] is not None else '?'}"
            print(f"  {l['plano'][:20]:20s} {l['ov']} {(l.get('ref') or ''):18s} {l.get('tipo_galva') or '':4s} ped {l.get('qty_pedida')}: {novo['origem']}{p}")


if __name__ == '__main__':
    main()
