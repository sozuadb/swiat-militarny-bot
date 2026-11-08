#!/usr/bin/env python3
"""
Script de autenticação única do YouTube Data API v3.
"""

import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")

def authenticate():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"[-] Erro: Arquivo {CLIENT_SECRETS_FILE} não encontrado!")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    print("\n" + "="*70)
    print("[*] Iniciando servidor de autenticação na porta 8080...")
    print("[*] Uma aba vai abrir no seu navegador para você autorizar o canal.")
    print("="*70 + "\n", flush=True)

    # run_local_server abre o browser e escuta o redirecionamento
    credentials = flow.run_local_server(
        host="localhost",
        port=8080,
        authorization_prompt_message="Abra a seguinte URL no navegador caso a aba não abra automaticamente:\n{url}\n",
        success_message="Autenticacao concluida com sucesso! Pode fechar esta janela.",
        open_browser=True,
        prompt="consent"
    )

    with open(TOKEN_FILE, "w") as token:
        token.write(credentials.to_json())

    print("\n" + "="*70)
    print(f"[+] SUCESSO TOTAL! Token permanente salvo em: {TOKEN_FILE}")
    print("[+] Acesso ao YouTube liberado para o bot!")
    print("="*70 + "\n", flush=True)
    return True

if __name__ == "__main__":
    authenticate()
