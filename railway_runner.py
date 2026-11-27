#!/usr/bin/env python3
"""
Runner contínuo 24/7 para Railway / Docker PaaS.
Injeta credenciais das variáveis de ambiente e roda o pipeline a cada 20 minutos.
"""

import os
import sys
import time
import logging
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

def pin_mymemory_host():
    hosts_path = Path("/etc/hosts")
    try:
        content = hosts_path.read_text(encoding="utf-8", errors="ignore")
        if "api.mymemory.translated.net" not in content:
            with open(hosts_path, "a", encoding="utf-8") as f:
                f.write("\n63.188.89.133 api.mymemory.translated.net\n")
            logging.info("[+] IP de alta disponibilidade fixado para api.mymemory.translated.net")
    except Exception as e:
        logging.warning(f"Não foi possível ajustar /etc/hosts: {e}")

def inject_env_credentials(force=False):
    token_json = os.environ.get("TOKEN_JSON")
    client_secrets = os.environ.get("CLIENT_SECRETS_JSON")
    cookies = os.environ.get("YOUTUBE_COOKIES")

    if token_json and (force or not (BASE_DIR / "token.json").exists()):
        (BASE_DIR / "token.json").write_text(token_json.strip(), encoding="utf-8")
        logging.info("[+] token.json injetado a partir da variável TOKEN_JSON")

    if client_secrets and (force or not (BASE_DIR / "client_secrets.json").exists()):
        (BASE_DIR / "client_secrets.json").write_text(client_secrets.strip(), encoding="utf-8")
        logging.info("[+] client_secrets.json injetado a partir da variável CLIENT_SECRETS_JSON")

    if cookies and (force or not (BASE_DIR / "cookies.txt").exists()):
        (BASE_DIR / "cookies.txt").write_text(cookies.strip(), encoding="utf-8")
        logging.info("[+] cookies.txt injetado a partir da variável YOUTUBE_COOKIES")

def sync_git_push():
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not gh_token or not (BASE_DIR / ".git").exists():
        return
    try:
        repo_url = f"https://x-access-token:{gh_token}@github.com/sozuadb/swiat-militarny-bot.git"
        subprocess.run(["git", "-C", str(BASE_DIR), "config", "user.name", "railway-bot"], check=False)
        subprocess.run(["git", "-C", str(BASE_DIR), "config", "user.email", "railway-bot@users.noreply.github.com"], check=False)
        subprocess.run(["git", "-C", str(BASE_DIR), "add", "processed_ids.json", "processed_shorts.json"], check=False)
        diff = subprocess.run(["git", "-C", str(BASE_DIR), "diff", "--cached", "--quiet"])
        if diff.returncode != 0:
            subprocess.run(["git", "-C", str(BASE_DIR), "commit", "-m", "chore: update processed IDs and shorts [skip ci]"], check=False)
            subprocess.run(["git", "-C", str(BASE_DIR), "pull", "--rebase", repo_url, "main"], check=False)
            subprocess.run(["git", "-C", str(BASE_DIR), "push", repo_url, "main"], check=False)
            logging.info("[+] Estado de processed_ids.json sincronizado com o GitHub.")
    except Exception as e:
        logging.warning(f"Falha ao sincronizar estado com GitHub: {e}")

def main():
    logging.info("=== INICIANDO RUNNER 24/7 SWIAT MILITARNY NO RAILWAY ===")
    pin_mymemory_host()
    inject_env_credentials(force=True)

    import run_once

    while True:
        try:
            inject_env_credentials(force=False)
            logging.info("Verificando se há novos vídeos no canal...")
            run_once.main()
        except SystemExit:
            pass
        except Exception as e:
            logging.error(f"Erro na execução da rodada: {e}", exc_info=True)
        finally:
            sync_git_push()

        logging.info("Aguardando 20 minutos (1200s) para a próxima verificação...")
        time.sleep(1200)

if __name__ == "__main__":
    main()
