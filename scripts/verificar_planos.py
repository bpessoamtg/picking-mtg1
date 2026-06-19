#!/usr/bin/env python3
"""
Verifica automaticamente se há novos planos de carga no Outlook
e carrega no Supabase do projeto Parque MTG1 Picking.
"""
import os
import json
import uuid
import base64
import sys
from datetime import datetime, timedelta, timezone
import requests

# ── Configuração ─────────────────────────────────────────────────────────
SUPABASE_URL = "https://cpoghfbbawubcmdtmpfj.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
MS_TENANT_ID  = os.environ["MS_TENANT_ID"]
MS_CLIENT_ID  = os.environ["MS_CLIENT_ID"]
MS_CLIENT_SECRET = os.environ["MS_CLIENT_SECRET"]
MS_REFRESH_TOKEN = os.environ["MS_REFRESH_TOKEN"]
MS_USER_EMAIL = os.environ.get("MS_USER_EMAIL", "brunopessoa@metalogalva.pt")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# ── Microsoft Graph — autenticação ───────────────────────────────────────
def get_ms_token():
    resp = requests.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "grant_type":    "refresh_token",
            "client_id":     MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "refresh_token": MS_REFRESH_TOKEN,
            "scope":         "https://graph.microsoft.com/Mail.Read offline_access",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def ms_get(token, path, params=None):
    resp = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=20,
    )
    return resp

# ── Pesquisa de emails ────────────────────────────────────────────────────
SEARCH_QUERIES = ["plano de carga", "plano carga", "planeamento", "expedição"]

def search_emails(token):
    seen = set()
    results = []
    for q in SEARCH_QUERIES:
        resp = ms_get(token, f"/users/{MS_USER_EMAIL}/messages", {
            "$search":  f'"{q}"',
            "$top":     "25",
            "$select":  "id,subject,receivedDateTime,hasAttachments,body",
        })
        if resp.status_code != 200:
            print(f"  Aviso: pesquisa '{q}' → {resp.status_code}")
            continue
        for msg in resp.json().get("value", []):
            if msg["id"] not in seen and msg.get("hasAttachments"):
                seen.add(msg["id"])
                results.append(msg)
    return results

def get_pdf_attachments(token, msg_id):
    resp = ms_get(token, f"/users/{MS_USER_EMAIL}/messages/{msg_id}/attachments")
    if resp.status_code != 200:
        return []
    return [
        a for a in resp.json().get("value", [])
        if a.get("name", "").lower().endswith(".pdf") and a.get("contentBytes")
    ]

# ── Supabase ──────────────────────────────────────────────────────────────
def plan_exists(nome):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/plans",
        headers=SUPABASE_HEADERS,
        params={"nome": f"eq.{nome}"},
        timeout=10,
    )
    return len(resp.json()) > 0

def insert_plan(plan):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/plans",
        headers=SUPABASE_HEADERS,
        data=json.dumps(plan, ensure_ascii=False).encode("utf-8"),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()[0]

def insert_items(items):
    for item in items:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/plan_items",
            headers=SUPABASE_HEADERS,
            data=json.dumps(item, ensure_ascii=False).encode("utf-8"),
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            print(f"  ✗ Erro item {item.get('model')}: {resp.text[:200]}")

# ── Análise com Claude ────────────────────────────────────────────────────
PROMPT = """Analisa este PDF de plano de carga e extrai as informações necessárias.

REGRAS DE FILTRAGEM — items MTG1:
- Incluir APENAS items onde Expedição contenha: CG, BG, TG ou AG
- Ignorar items com Expedição CP ou BP (são pintados)
- Incluir APENAS Referências que comecem por CI ou CC, OU que terminem em "_V"
- Exceção: CEC* ou CAO* incluir se Expedição for CG ou BG

MAPEAMENTO DE CAMPOS:
- model     = coluna Mat.Entrado / DGERAL (código do produto, ex: CBO4E10D) — NUNCA o código SAP
- ref       = coluna Referencia / REFERENCIA (código SAP, ex: CI68MF02G)
- desc_item = coluna Descrição
- tipo_galva = CG, BG, TG ou AG (da coluna Expedição)
- ov        = coluna OV
- descarga  = coluna Descarga ou Nome Recebedor
- qty_pedida = coluna Qty (número inteiro)

CORPO DO EMAIL (para data/hora):
{email_body}

DATA DE RECEÇÃO DO EMAIL: {received_date}

DATA DE CARGA:
- "amanhã"/"amanha" → data_receção + 1 dia
- "hoje" → data_receção
- Dia da semana ou data explícita mencionada → usar essa data
- Caso contrário → data_receção

HORA DE CARGA (hora_carregar):
- "manhã"/"manha"/"de manhã" → "10:00"
- "tarde"/"à tarde"/"de tarde" → "14:00"
- "mtg4"/"Metalogalva 4" antes da MTG1 → "16:00"
- Hora explícita "às 8h", "8:00", "14h00" → "HH:MM"
- Não determinável → null

GRUPO:
- "colunas"    se todos os items forem CG
- "acessorios" se todos forem BG/AG/TG
- "ambos"      se mistura

HTML TABLE: Gera uma tabela HTML com TODAS as linhas do PDF (não só MTG1).
Colunas originais: Status, Descarga, Nome, OV, Item, Referência, Mat.Entrado, Descrição, Qty, Expedição.
Linhas MTG1 com style="background:#dcfce7" e um <span style="background:#16a34a;color:#fff;padding:2px 6px;border-radius:4px;font-size:11px">MTG1</span> na primeira célula.
Apenas a tag <table>...</table>, sem html/head/body.

Responde APENAS com JSON válido, sem texto adicional:
{{
  "nome_plano": "nome extraído do assunto do email ou do PDF",
  "data": "YYYY-MM-DD",
  "hora_carregar": "HH:MM ou null",
  "grupo": "colunas|acessorios|ambos",
  "items": [
    {{
      "model": "...",
      "ref": "...",
      "desc_item": "...",
      "tipo_galva": "CG|BG|TG|AG",
      "ov": "...",
      "descarga": "...",
      "qty_pedida": 0
    }}
  ],
  "html_table": "<table>...</table>"
}}"""

def analyze_with_claude(pdf_b64, subject, email_body, received_date):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type":       "base64",
                        "media_type": "application/pdf",
                        "data":       pdf_b64,
                    },
                },
                {
                    "type": "text",
                    "text": PROMPT.format(
                        email_body=email_body[:2000],
                        received_date=received_date,
                    ),
                },
            ],
        }],
    )

    text = msg.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    start = text.find("{")
    end   = text.rfind("}") + 1
    return json.loads(text[start:end])

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    print(f"=== Verificar Planos de Carga — {datetime.now(timezone.utc).isoformat()} ===\n")

    token = get_ms_token()
    print("✓ Autenticado no Microsoft Graph")

    emails = search_emails(token)
    print(f"✓ {len(emails)} email(s) com anexos encontrado(s)\n")

    loaded, ignored, existing = [], [], []

    for msg in emails:
        subject  = msg.get("subject", "").strip()
        received = msg.get("receivedDateTime", "")[:10]
        body     = msg.get("body", {}).get("content", "")

        attachments = get_pdf_attachments(token, msg["id"])
        if not attachments:
            continue

        for att in attachments:
            # Check if plan already exists (using subject as name first)
            if plan_exists(subject):
                if subject not in existing:
                    existing.append(subject)
                    print(f"  ↷ Já existe: {subject}")
                continue

            print(f"  → A analisar: {subject}")

            try:
                result = analyze_with_claude(att["contentBytes"], subject, body, received)
            except Exception as e:
                print(f"  ✗ Erro Claude: {e}")
                continue

            plan_name = result.get("nome_plano") or subject
            items = result.get("items", [])

            # Re-check with the extracted plan name
            if plan_exists(plan_name):
                if plan_name not in existing:
                    existing.append(plan_name)
                    print(f"  ↷ Já existe (nome extraído): {plan_name}")
                continue

            if not items:
                ignored.append(plan_name)
                print(f"  ✗ Sem items MTG1: {plan_name}")
                continue

            # Build html base64
            html_content = result.get("html_table", "<p>Sem conteúdo</p>")
            html_b64     = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
            pdf_field    = f"data:text/html;base64,{html_b64}"

            plan_id = str(uuid.uuid4())
            hora    = result.get("hora_carregar")
            if hora == "null" or hora == "":
                hora = None

            plan = {
                "id":           plan_id,
                "nome":         plan_name,
                "tipo":         "carga",
                "data":         result.get("data", received),
                "hora_carregar": hora,
                "status":       "em_separacao",
                "grupo":        result.get("grupo", "ambos"),
                "criado_por":   "auto",
                "criado_em":    datetime.now(timezone.utc).isoformat(),
                "pdf_base64":   pdf_field,
            }

            try:
                insert_plan(plan)
            except Exception as e:
                print(f"  ✗ Erro inserir plano: {e}")
                continue

            plan_items = []
            for it in items:
                plan_items.append({
                    "id":          str(uuid.uuid4()),
                    "plan_id":     plan_id,
                    "model":       it.get("model", ""),
                    "ref":         it.get("ref", ""),
                    "desc_item":   it.get("desc_item", ""),
                    "tipo_galva":  it.get("tipo_galva", "CG"),
                    "ov":          it.get("ov", ""),
                    "descarga":    it.get("descarga", ""),
                    "qty_pedida":  int(it.get("qty_pedida") or 0),
                    "qty_separada": 0,
                    "separado":    False,
                    "entregue":    False,
                })

            insert_items(plan_items)
            loaded.append(f"{plan_name} ({len(plan_items)} items)")
            print(f"  ✓ Carregado: {plan_name} — {len(plan_items)} item(s) MTG1")

    print("\n=== RESUMO ===")
    if loaded:
        print(f"Planos novos ({len(loaded)}):       {', '.join(loaded)}")
    if ignored:
        print(f"Sem items MTG1 ({len(ignored)}):   {', '.join(ignored)}")
    if existing:
        print(f"Já existentes ({len(existing)}):   {', '.join(existing)}")
    if not loaded and not ignored and not existing:
        print("Nenhum plano novo encontrado.")
    print()

if __name__ == "__main__":
    main()
