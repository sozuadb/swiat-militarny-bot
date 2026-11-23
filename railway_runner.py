#!/usr/bin/env python3
"""
Runner contínuo 24/7 para Railway / Docker PaaS.
Injeta credenciais das variáveis de ambiente e roda o pipeline a cada 20 minutos.
"""

import os
import sys
import time
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

def inject_env_credentials():
    token_json = os.environ.get("TOKEN_JSON")
    client_secrets = os.environ.get("CLIENT_SECRETS_JSON")
    cookies = os.environ.get("YOUTUBE_COOKIES")

    if token_json and not (BASE_DIR / "token.json").exists():
        (BASE_DIR / "token.json").write_text(token_json.strip(), encoding="utf-8")
        logging.info("[+] token.json injetado a partir da variável TOKEN_JSON")

    if client_secrets and not (BASE_DIR / "client_secrets.json").exists():
        (BASE_DIR / "client_secrets.json").write_text(client_secrets.strip(), encoding="utf-8")
        logging.info("[+] client_secrets.json injetado a partir da variável CLIENT_SECRETS_JSON")

    if cookies and not (BASE_DIR / "cookies.txt").exists():
        (BASE_DIR / "cookies.txt").write_text(cookies.strip(), encoding="utf-8")
        logging.info("[+] cookies.txt injetado a partir da variável YOUTUBE_COOKIES")

def main():
    logging.info("=== INICIANDO RUNNER 24/7 SWIAT MILITARNY NO RAILWAY ===")
    inject_env_credentials()

    import run_once

    while True:
        try:
            inject_env_credentials()
            logging.info("Verificando se há novos vídeos no canal...")
            run_once.main()
        except SystemExit:
            pass
        except Exception as e:
            logging.error(f"Erro na execução da rodada: {e}", exc_info=True)

        logging.info("Aguardando 20 minutos (1200s) para a próxima verificação...")
        time.sleep(1200)

if __name__ == "__main__":
    main()
