"""Grava o código de material SAP nas linhas dos planos de pintura.

As linhas de pintura são coladas na app com o modelo comercial (CBCBE06DI) e
sem código SAP. O material está na linha da OV no SAP, com o modelo no texto
("CBCBE06DI", "Col. Con. CBCRF45DI", "Braço DRV R60KC150S2") ou como o próprio
código (CFC1F07RI_V). Com o código gravado, a app mostra o stock SAP do
material exato da OV e o código no modal de quantidade.

Dois passos, porque o SAP só se lê pela consulta guardada:
  1) python preencher_ref_pintura.py --listar-ovs
     imprime a lista JSON das OVs com linhas de pintura sem código
  2) correr a consulta guardada linhas_ov_mt01 com essa lista (exportar json)
  3) python preencher_ref_pintura.py <export.json> [--aplicar]
     sem --aplicar só mostra o que faria

Só preenche linhas sem código; nunca altera um código já gravado. Uma linha
fica por preencher quando o modelo não aparece na OV ou aparece com mais do
que um material diferente.
"""
import argparse
import datetime
import json
import re
import sys
import urllib.parse
import urllib.request

SUPABASE_URL = 'https://cpoghfbbawubcmdtmpfj.supabase.co'
ANON_KEY = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwb2do'
            'ZmJiYXd1YmNtZHRtcGZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA0MDUzMDYsImV4cCI6MjA5'
            'NTk4MTMwNn0.fdInpb2SViVNmSg7VR0cYDK6qkGROfFm5OWGTBi8ORA')

# Linhas da OV que nunca são a peça a pintar: cabeçalho genérico do conjunto,
# serviço de pintura, diversos (etiquetas) e acessórios de montagem.
NAO_PECA = re.compile(r'^(CI100000G|CIDIV|DTP|ID\d)')


def pedido(metodo, caminho, corpo=None):
    h = {'apikey': ANON_KEY, 'Authorization': 'Bearer ' + ANON_KEY, 'Content-Type': 'application/json'}
    if metodo == 'PATCH':
        h['Prefer'] = 'return=minimal'
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(SUPABASE_URL + '/rest/v1' + caminho, data=dados, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=60) as r:
        txt = r.read().decode('utf-8')
        return json.loads(txt) if txt else None


def linhas_sem_codigo(dias):
    # Só os planos recentes: as linhas que o SAP não resolve (texto livre,
    # modelo ambíguo) não voltam a ser pedidas para sempre
    desde = (datetime.date.today() - datetime.timedelta(days=dias)).isoformat()
    planos = pedido('GET', '/plans?tipo=eq.pintura&data=gte.' + desde + '&select=id,nome,plan_items(id,ov,ref,model)')
    out = []
    for p in planos:
        for i in p['plan_items']:
            if (i.get('ref') or '').strip():
                continue
            ov = (i.get('ov') or '').strip()
            modelo = (i.get('model') or '').strip().upper()
            if ov.isdigit() and modelo:
                out.append({'id': i['id'], 'ov': ov.lstrip('0'), 'modelo': modelo, 'plano': p['nome']})
    return out


def material_para(modelo, linhas_ov):
    cand = set()
    for mat, texto in linhas_ov:
        if NAO_PECA.match(mat):
            continue
        ultima = texto.split()[-1].upper() if texto.split() else ''
        if mat == modelo or ultima == modelo or texto.upper() == modelo:
            cand.add(mat)
    return cand.pop() if len(cand) == 1 else (None if not cand else 'AMBIGUO')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('export', nargs='?')
    ap.add_argument('--listar-ovs', action='store_true')
    ap.add_argument('--aplicar', action='store_true')
    ap.add_argument('--dias', type=int, default=14, help='planos com data nos últimos N dias (ou futura)')
    a = ap.parse_args()

    linhas = linhas_sem_codigo(a.dias)
    if a.listar_ovs:
        ovs = sorted({l['ov'].zfill(10) for l in linhas})
        print(json.dumps(ovs))
        return
    if not a.export:
        sys.exit('Falta o ficheiro exportado da consulta linhas_ov_mt01 (ou --listar-ovs).')

    d = json.load(open(a.export, encoding='utf-8'))
    cols = [c['nome'] for c in d['colunas']]
    iov, imat, itxt = cols.index('OV'), cols.index('MATERIAL'), cols.index('TEXTO')
    por_ov = {}
    for r in d['linhas']:
        por_ov.setdefault(str(r[iov]).lstrip('0'), []).append((str(r[imat]).strip().upper(), str(r[itxt] or '').strip()))

    feitas, ambiguas, sem_ov, sem_modelo = [], [], 0, []
    for l in linhas:
        lo = por_ov.get(l['ov'])
        if lo is None:
            sem_ov += 1
            continue
        m = material_para(l['modelo'], lo)
        if m == 'AMBIGUO':
            ambiguas.append(l)
        elif m:
            feitas.append((l, m))
        else:
            sem_modelo.append(l)

    if a.aplicar:
        for l, m in feitas:
            pedido('PATCH', '/plan_items?id=eq.' + urllib.parse.quote(str(l['id'])) + '&ref=is.null', {'ref': m})

    acao = 'gravados' if a.aplicar else 'a gravar (ensaio, usar --aplicar)'
    diferentes = sum(1 for l, m in feitas if m != l['modelo'])
    print(f'Códigos SAP nas linhas de pintura: {len(feitas)} {acao} '
          f'({diferentes} com código diferente do modelo), {len(sem_modelo)} sem o modelo na OV, '
          f'{len(ambiguas)} com mais do que um material, {sem_ov} sem OV no SAP -- de {len(linhas)} linhas sem código')
    if not a.aplicar:
        for l, m in feitas[:15]:
            print(f'  {l["ov"]} {l["modelo"]} -> {m}')
        for l in sem_modelo[:15]:
            print(f'  sem modelo: {l["ov"]} {l["modelo"]}')
        for l in ambiguas[:10]:
            print(f'  ambíguo: {l["ov"]} {l["modelo"]}')


if __name__ == '__main__':
    main()
