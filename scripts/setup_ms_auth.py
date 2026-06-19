#!/usr/bin/env python3
"""
Executa UMA VEZ para obter o refresh_token da Microsoft para guardar no GitHub.

Pré-requisitos:
  1. Criar uma App Registration no Azure AD (portal.azure.com)
  2. Em "Authentication": adicionar "Mobile and desktop applications" com
     redirect URI: https://login.microsoftonline.com/common/oauth2/nativeclient
  3. Em "API permissions": adicionar Microsoft Graph → Delegated → Mail.Read
  4. Em "Certificates & secrets": criar um Client secret (copiar o Value)
  5. Preencher as variáveis abaixo e correr: python scripts/setup_ms_auth.py

O script vai imprimir o refresh_token para guardar como secret no GitHub.

pip install requests
"""
import requests
import json

# ── PREENCHER ────────────────────────────────────────────────────────────
CLIENT_ID     = "COLE_AQUI_O_APPLICATION_CLIENT_ID"
CLIENT_SECRET = "COLE_AQUI_O_CLIENT_SECRET"
TENANT_ID     = "COLE_AQUI_O_TENANT_ID"   # ou "common" se não souberes
# ─────────────────────────────────────────────────────────────────────────

SCOPE = "https://graph.microsoft.com/Mail.Read offline_access"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
DEVICE_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/devicecode"

# 1. Pedir device code
resp = requests.post(DEVICE_URL, data={
    "client_id": CLIENT_ID,
    "scope":     SCOPE,
})
resp.raise_for_status()
data = resp.json()

print("\n" + "="*60)
print("PASSO 1: Abre este URL no browser e introduz o código abaixo")
print("="*60)
print(f"URL:    {data['verification_uri']}")
print(f"Código: {data['user_code']}")
print("="*60)
input("\nQuando tiveres feito o login, prime ENTER aqui para continuar...\n")

# 2. Trocar device code por tokens
resp2 = requests.post(TOKEN_URL, data={
    "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
    "client_id":   CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "device_code": data["device_code"],
})
resp2.raise_for_status()
tokens = resp2.json()

print("\n" + "="*60)
print("SUCESSO! Guarda estes valores como secrets no GitHub:")
print("="*60)
print(f"\nMS_TENANT_ID:     {TENANT_ID}")
print(f"MS_CLIENT_ID:     {CLIENT_ID}")
print(f"MS_CLIENT_SECRET: {CLIENT_SECRET}")
print(f"MS_REFRESH_TOKEN: {tokens['refresh_token']}")
print("\nSUPABASE_KEY: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwb2doZmJiYXd1YmNtZHRtcGZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA0MDUzMDYsImV4cCI6MjA5NTk4MTMwNn0.fdInpb2SViVNmSg7VR0cYDK6qkGROfFm5OWGTBi8ORA")
print("MS_USER_EMAIL:    brunopessoa@metalogalva.pt")
print("="*60)
print("\nVai a: https://github.com/bpessoamtg/picking-mtg1/settings/secrets/actions")
print("e adiciona cada um destes como 'Repository secret'.\n")
