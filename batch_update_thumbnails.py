#!/usr/bin/env python3
"""
Atualiza em lote as thumbnails dos vídeos restantes assim que a cota diária resetar.
"""

import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from upload import get_authenticated_service
from googleapiclient.http import MediaFileUpload
from thumbnail_generator import generate_localized_thumbnail

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp_thumbs"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 1 vídeo pendente de reset de cota do YouTube
VIDEOS_PENDING = [
    ("sTB7BYPaisU", "NTmsCRGCzY0", "Japonia chce broni jądrowej? Koniec powojennego tabu w Tokio"),
]

def update_pending():
    print(f"[*] Processando {len(VIDEOS_PENDING)} thumbnails pendentes...")
    yt = get_authenticated_service()

    for idx, (orig_id, pub_id, title_pl) in enumerate(VIDEOS_PENDING, 1):
        print(f"\n[{idx}/{len(VIDEOS_PENDING)}] Processando {pub_id} (orig: {orig_id})...")
        orig_thumb_prefix = TEMP_DIR / f"orig_{orig_id}"
        
        cmd = [
            "/home/souza/canal_polones/venv/bin/yt-dlp",
            "--js-runtimes", "node:/usr/bin/node",
            "--cookies", "/home/souza/canal_polones/cookies.txt",
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "--skip-download",
            "-o", f"{orig_thumb_prefix}.%(ext)s",
            f"https://www.youtube.com/watch?v={orig_id}"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        orig_jpg = TEMP_DIR / f"orig_{orig_id}.jpg"
        if not orig_jpg.exists():
            for cand in TEMP_DIR.glob(f"orig_{orig_id}*"):
                if cand.suffix.lower() in [".jpg", ".webp", ".png"]:
                    subprocess.run(["ffmpeg", "-y", "-i", str(cand), str(orig_jpg)], capture_output=True)
                    break

        if not orig_jpg.exists():
            print(f"[!] Falha ao obter thumbnail para {orig_id}")
            continue

        loc_jpg = TEMP_DIR / f"loc_{pub_id}.jpg"
        ok = generate_localized_thumbnail(orig_jpg, title_pl, loc_jpg)
        if not ok or not loc_jpg.exists():
            print(f"[!] Falha ao gerar thumbnail localizada para {pub_id}")
            continue

        try:
            print(f"[*] Enviando nova thumbnail para {pub_id}...")
            media = MediaFileUpload(str(loc_jpg), mimetype="image/jpeg", resumable=True)
            res_api = yt.thumbnails().set(videoId=pub_id, media_body=media).execute()
            print(f"[+] SUCESSO! Thumbnail atualizada no YouTube para {pub_id}")
        except Exception as e:
            print(f"[!] Erro ao atualizar thumbnail no YouTube para {pub_id}: {e}")

        time.sleep(1.0)

    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    print("\n[+] Finalizado!")

if __name__ == "__main__":
    update_pending()
