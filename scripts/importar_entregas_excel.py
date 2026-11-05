# -*- coding: utf-8 -*-
"""Copia para a app de picking as entregas à pintura registadas nos Excel da expedição.

- Colunas: Expedição_Colunas_2026.xlsm, separador "Kanban" (OV, MODELO, QUANTIDADE, DATA, OPERADOR)
- Braços:  Expedição_braços_2026.xlsm, separador "Pintura Kanban" (OV, MODELO, QUANTIDADE, DATA, OPERADOR)

Cada Excel substitui por inteiro as suas entregas na base de dados (função
importar_entregas_excel, sql/entregas_excel.sql), que recusa leituras muito
mais pequenas do que as já gravadas. Com --se-mudou, só copia um Excel que
mudou desde a última cópia (guarda a data do ficheiro em
scripts/estado_entregas_excel.json).

Imprime uma linha por Excel. Sai com código 1 se algum falhar.
"""
import argparse
import datetime
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

import openpyxl

SUPABASE_URL = 'https://cpoghfbbawubcmdtmpfj.supabase.co'
ANON_KEY = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwb2do'
            'ZmJiYXd1YmNtZHRtcGZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA0MDUzMDYsImV4cCI6MjA5NTk4'
            'MTMwNn0.fdInpb2SViVNmSg7VR0cYDK6qkGROfFm5OWGTBi8ORA')

BASE = os.path.join(os.path.expanduser('~'), 'OneDrive - METALOGALVA - IRMÃOS SILVAS, S.A',
                    'Ficheiros de David Ribeiro - DL', 'Expedição')
EXCEL = {
    'colunas':    (os.path.join(BASE, 'Colunas', 'Expedição_Colunas_2026.xlsm'), 'Kanban'),
    'acessorios': (os.path.join(BASE, 'Braços', 'Expedição_braços_2026.xlsm'), 'Pintura Kanban'),
}
ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'estado_entregas_excel.json')


def ler_linhas(caminho, separador):
    # Lê uma cópia: o Excel pode estar aberto (e a sincronizar) noutro lado
    tmp = os.path.join(tempfile.mkdtemp(), 'copia.xlsm')
    shutil.copy2(caminho, tmp)
    try:
        ws = openpyxl.load_workbook(tmp, read_only=True, data_only=True)[separador]
        linhas_ws = ws.iter_rows(values_only=True)
        cab = [str(c or '').strip().upper() for c in next(linhas_ws)]
        col = {nome: cab.index(nome) for nome in ('OV', 'MODELO', 'QUANTIDADE', 'DATA', 'OPERADOR')}
        linhas = []
        for r in linhas_ws:
            ov, data = r[col['OV']], r[col['DATA']]
            if ov is None or not isinstance(data, datetime.datetime):
                continue
            q = r[col['QUANTIDADE']]
            linhas.append({
                'ov': str(int(ov)) if isinstance(ov, (int, float)) else str(ov).strip(),
                'modelo': str(r[col['MODELO']] or '').strip(),
                'quantidade': int(q) if isinstance(q, (int, float)) else None,
                'data': data.date().isoformat(),
                'operador': str(r[col['OPERADOR']] or '').strip() or None,
            })
        return linhas
    finally:
        shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)


def importar(grupo, linhas):
    corpo = json.dumps({'p_grupo': grupo, 'p_linhas': linhas}).encode('utf-8')
    req = urllib.request.Request(
        SUPABASE_URL + '/rest/v1/rpc/importar_entregas_excel', data=corpo, method='POST',
        headers={'apikey': ANON_KEY, 'Authorization': 'Bearer ' + ANON_KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--se-mudou', action='store_true', help='só copia os Excel que mudaram desde a última cópia')
    args = ap.parse_args()

    try:
        estado = json.load(open(ESTADO, encoding='utf-8'))
    except (OSError, ValueError):
        estado = {}

    falhou = False
    for grupo, (caminho, separador) in EXCEL.items():
        nome = os.path.basename(caminho)
        try:
            mtime = os.path.getmtime(caminho)
            if args.se_mudou and estado.get(grupo) == mtime:
                print(f'Entregas Excel {grupo}: sem alterações desde a última cópia ({nome})')
                continue
            linhas = ler_linhas(caminho, separador)
            r = importar(grupo, linhas)
            estado[grupo] = mtime
            print(f'Entregas Excel {grupo}: {r["agora"]} entregas copiadas (antes {r["antes"]}) de {nome}')
        except urllib.error.HTTPError as e:
            falhou = True
            print(f'Entregas Excel {grupo}: NÃO copiado — {e.read().decode("utf-8", "replace")[:200]}')
        except Exception as e:  # ficheiro em falta, separador mudado, sem rede...
            falhou = True
            print(f'Entregas Excel {grupo}: NÃO copiado — {type(e).__name__}: {e}')

    with open(ESTADO, 'w', encoding='utf-8') as f:
        json.dump(estado, f)
    sys.exit(1 if falhou else 0)


if __name__ == '__main__':
    main()
