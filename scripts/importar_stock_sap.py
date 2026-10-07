"""Importa a extração diária de stock do SAP (ZMB52) para a tabela stock_sap.

O SAP envia todos os dias um email "Job STOCKS LOGISTICA MTG 1, Step 1" com a
lista de stock em PDF. A rotina verificar-planos-carga lê o anexo pelo conector
do Outlook, que devolve o PDF como texto (células separadas por 3+ espaços), e
corre este script sobre esse texto. Também aceita o próprio PDF.

Faz o mesmo que o botão "Importar extração" do Dashboard: soma os lotes de cada
material, grava tudo de uma vez e apaga os materiais que já não vêm na lista.

Nunca grava uma leitura que não bata certo: o rodapé do relatório traz o total
por unidade ("* 260 UN" e "35,150.000 UN."), e a soma lida tem de ser igual.

Uso:
  python importar_stock_sap.py FICHEIRO [--tag TEXTO] [--se-novo] [--simular]

  --tag      fica em atualizado_por (ex.: "Email SAP 2026-10-07T08:47:58Z")
  --se-novo  não faz nada se a última importação já tiver esta tag
  --simular  lê e valida, mas não escreve
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
            'ZmJiYXd1YmNtZHRtcGZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA0MDUzMDYsImV4cCI6MjA5NTk4'
            'MTMwNn0.fdInpb2SViVNmSg7VR0cYDK6qkGROfFm5OWGTBi8ORA')

UNIDADES = ('UN', 'UN.')
# Lotes vistos no ZMB52: "EI", "CP0ASA04" e números de 10 dígitos. Só serve para
# separar descrição de lote quando uma das duas vem vazia -- nunca mexe na quantidade.
LOTE = re.compile(r'^(EI|\d{10}|CP[0-9A-Z]{6})$')
CABECALHO = re.compile(r'\d{2}\.\d{2}\.\d{4}\s+Display Warehouse Stocks of Material\s+\d+\s+'
                       r'Material\s+Plnt\s+Material Description\s+Batch\s+Loca\s+Unrestricted\s+BUn\s+'
                       r'Value Unrestricted\s+Crcy\s+Last GR\s+Blocked')


class LeituraInvalida(Exception):
    pass


def numero(s):
    """'1,009.000' (EN) ou '1.009,000' (PT) -> 1009.0. Com 3 decimais fixos, um
    separador sozinho é sempre decimal."""
    s = s.strip().replace(' ', '').replace(' ', '')
    if ',' in s and '.' in s:
        dec = '.' if s.rfind('.') > s.rfind(',') else ','
        s = s.replace(',' if dec == '.' else '.', '').replace(dec, '.')
    elif ',' in s or '.' in s:
        ch = ',' if ',' in s else '.'
        partes = s.split(ch)
        s = ''.join(partes) if len(partes) > 2 else partes[0] + '.' + partes[1]
    return float(s)


def eh_numero(s):
    return bool(re.fullmatch(r'-?[\d.,]+', s.strip())) and any(c.isdigit() for c in s)


def ler_texto(texto):
    """Texto do conector do Outlook: uma linha por página, células separadas por
    3+ espaços, células vazias omitidas."""
    data = re.search(r'(\d{2}\.\d{2}\.\d{4})\s+Display Warehouse', texto)
    corpo = CABECALHO.sub('   ', texto.replace('\r', ' ').replace('\n', '   '))
    cel = [c.strip() for c in re.split(r'\s{3,}', corpo) if c.strip()]

    linhas, i = [], 0
    while i < len(cel) - 1:
        if cel[i + 1] != 'MT01' or cel[i] == '*':
            i += 1
            continue
        # quantidade = célula imediatamente antes da unidade
        k = next((j for j in range(i + 2, min(i + 8, len(cel) - 1))
                  if cel[j + 1] in UNIDADES and eh_numero(cel[j])), None)
        if k is None:
            raise LeituraInvalida(f'linha sem quantidade junto de {cel[i]!r}')
        # Descrição e lote (sem o "01"). Há descrições com 3 espaços lá dentro
        # ("Top Extension poles 76 1000   N142940"), que chegam partidas em várias
        # células: o lote é só a última, e só se tiver forma de lote.
        meio = cel[i + 2:k - 1]
        if meio and LOTE.match(meio[-1]):
            lote, desc = meio[-1], ' '.join(meio[:-1])
        else:
            lote, desc = '', ' '.join(meio)
        # O fim da linha anterior cola ao material com um só espaço ("0.000 CI48UF02G")
        ref = cel[i].split()[-1].upper()
        linhas.append({'ref': ref, 'desc': desc, 'lote': lote,
                       'qty': numero(cel[k]), 'un': cel[k + 1]})
        i = k + 2

    rodape = texto[texto.rfind('*'):] if '*' in texto else ''
    totais = {}
    for qtd, un in re.findall(r'([\d.,]+)\s+(UN\.?)(?![\w.])', rodape):
        totais[un] = numero(qtd)
    return linhas, totais, data.group(1) if data else None


def ler_pdf(caminho):
    """O PDF tal como vem no email: as colunas lêem-se pela posição na página."""
    import collections
    import pdfplumber
    linhas, totais, data = [], {}, None
    with pdfplumber.open(caminho) as pdf:
        for pg in pdf.pages:
            grupos = collections.defaultdict(list)
            for w in pg.extract_words():
                grupos[round(w['top'] / 3)].append(w)
            for k in sorted(grupos):
                ws = sorted(grupos[k], key=lambda w: w['x0'])
                if data is None and re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', ws[0]['text']):
                    data = ws[0]['text']
                if ws[0]['top'] < 45:
                    continue
                col = lambda a, b: [w['text'] for w in ws if a <= w['x0'] < b]
                mat, plant = col(0, 105), col(105, 131)
                qty = [w['text'] for w in ws if w['x0'] >= 380 and 420 <= w['x1'] <= 437]
                un = col(437, 457)
                if mat == ['*'] or (not mat and un):
                    for q, u in zip(qty, un):
                        totais[u] = numero(q)
                    continue
                if len(mat) == 1 and plant == ['MT01'] and len(qty) == 1 and un:
                    linhas.append({'ref': mat[0].upper(), 'desc': ' '.join(col(131, 310)),
                                   'lote': ' '.join(col(310, 358)), 'qty': numero(qty[0]), 'un': un[0]})
    return linhas, totais, data


def validar(linhas, totais):
    if len(linhas) < 100:
        raise LeituraInvalida(f'só {len(linhas)} linhas lidas -- extração incompleta?')
    if not totais:
        raise LeituraInvalida('rodapé com os totais não encontrado')
    somas = {}
    for r in linhas:
        somas[r['un']] = somas.get(r['un'], 0) + r['qty']
    for un in set(somas) | set(totais):
        if abs(somas.get(un, 0) - totais.get(un, 0)) > 0.001:
            raise LeituraInvalida(f'soma em {un} = {somas.get(un, 0):g}, rodapé diz {totais.get(un, 0):g}')
    return somas


def agregar(linhas):
    """Soma os lotes de cada material, como o import do Dashboard."""
    agg = {}
    for r in linhas:
        a = agg.setdefault(r['ref'], {'ref': r['ref'], 'descricao': r['desc'], 'quantidade': 0.0})
        a['quantidade'] += r['qty']
        if not a['descricao']:
            a['descricao'] = r['desc']
    for a in agg.values():
        a['quantidade'] = round(a['quantidade'])
    return list(agg.values())


def pedido(metodo, caminho, corpo=None, prefer=None):
    h = {'apikey': ANON_KEY, 'Authorization': 'Bearer ' + ANON_KEY, 'Content-Type': 'application/json'}
    if prefer:
        h['Prefer'] = prefer
    dados = json.dumps(corpo).encode('utf-8') if corpo is not None else None
    req = urllib.request.Request(SUPABASE_URL + '/rest/v1' + caminho, data=dados, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=60) as r:
        txt = r.read().decode('utf-8')
        return json.loads(txt) if txt else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ficheiro')
    ap.add_argument('--tag', default='Email SAP')
    ap.add_argument('--se-novo', action='store_true')
    ap.add_argument('--simular', action='store_true')
    a = ap.parse_args()

    if a.se_novo and not a.simular:
        ultima = pedido('GET', '/stock_sap?select=atualizado_por&order=atualizado_em.desc&limit=1')
        if ultima and ultima[0].get('atualizado_por') == a.tag:
            print(f'Stock SAP: já importado ({a.tag}) -- nada a fazer.')
            return 0

    try:
        if a.ficheiro.lower().endswith('.pdf'):
            linhas, totais, data = ler_pdf(a.ficheiro)
        else:
            with open(a.ficheiro, encoding='utf-8') as f:
                linhas, totais, data = ler_texto(f.read())
        somas = validar(linhas, totais)
    except LeituraInvalida as e:
        print(f'Stock SAP: NÃO importado -- leitura não bate certo: {e}')
        return 2

    materiais = agregar(linhas)
    total = sum(m['quantidade'] for m in materiais)
    resumo = (f'{len(linhas)} linhas, {len(materiais)} materiais, {total:,} un. '
              f'(rodapé: {", ".join(f"{v:,.0f} {k}" for k, v in sorted(somas.items()))}) '
              f'-- extração de {data or "?"}').replace(',', ' ')

    if a.simular:
        print('Stock SAP (simulação, nada gravado): ' + resumo)
        return 0

    atuais = pedido('GET', '/stock_sap?select=ref,descricao&limit=10000') or []
    # Uma extração com muito menos materiais do que a anterior é mais provável ser
    # um relatório cortado do que o parque ter esvaziado: não se apaga meio stock.
    if atuais and len(materiais) < 0.6 * len(atuais):
        print(f'Stock SAP: NÃO importado -- só {len(materiais)} materiais contra {len(atuais)} na base de dados.')
        return 3
    # O PDF às vezes traz a descrição vazia; fica a que já estava guardada
    desc_antiga = {r['ref']: r.get('descricao') or '' for r in atuais}
    for m in materiais:
        if not m['descricao']:
            m['descricao'] = desc_antiga.get(m['ref'], '')

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload = [{**m, 'atualizado_em': ts, 'atualizado_por': a.tag} for m in materiais]
    # Upsert e só depois limpeza do que ficou para trás: se falhar a meio, nunca
    # fica uma tabela vazia a dizer aos operadores que não há stock de nada.
    for i in range(0, len(payload), 200):
        pedido('POST', '/stock_sap', payload[i:i + 200], prefer='return=minimal,resolution=merge-duplicates')
    pedido('DELETE', '/stock_sap?atualizado_em=lt.' + urllib.parse.quote(ts), prefer='return=minimal')
    print('Stock SAP importado: ' + resumo)
    return 0


if __name__ == '__main__':
    sys.exit(main())
