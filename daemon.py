#!/usr/bin/env python3
"""
Daemon Autônomo 24/7 - Canal 'Świat Militarny'
Monitora o canal '@hojenomundomilitar', baixa novos vídeos, corta vinheta e patrocinador,
traduz para polonês, gera áudio neural Marek, renderiza e publica no YouTube automaticamente.
"""

import os
import sys
import time
import json
import re
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi
from deep_translator import MyMemoryTranslator

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
PROCESSED_FILE = BASE_DIR / "processed_ids.json"
LOG_FILE = BASE_DIR / "daemon.log"
VAULT_SESSIONS_DIR = Path("/home/souza/Vault/01 - Conversas & Sessões")
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
VENV_EDGE_TTS = BASE_DIR / "venv" / "bin" / "edge-tts"
UPLOAD_SCRIPT = BASE_DIR / "upload.py"

TARGET_CHANNEL = "https://www.youtube.com/@hojenomundomilitar/videos"
CHECK_INTERVAL_SECONDS = 1200 # 20 minutos

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

def run_cmd(cmd, check=True):
    cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
    logging.info(f"Executando: {cmd_str}")
    res = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if check and res.returncode != 0:
        logging.error(f"Erro no comando:\nSTDERR: {res.stderr}\nSTDOUT: {res.stdout}")
        raise RuntimeError(f"Comando falhou: {cmd_str}")
    return res

def load_processed_ids():
    if PROCESSED_FILE.exists():
        try:
            with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            logging.error(f"Erro ao ler {PROCESSED_FILE}: {e}")
    return set()

def save_processed_id(video_id):
    current = load_processed_ids()
    current.add(video_id)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(current), f, indent=2, ensure_ascii=False)
    logging.info(f"ID {video_id} salvo em {PROCESSED_FILE}")

def get_latest_channel_video_ids(limit=3):
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(limit), "--print", "%(id)s", TARGET_CHANNEL]
    res = run_cmd(cmd, check=False)
    if res.returncode != 0:
        logging.warning("Falha ao checar canal com yt-dlp")
        return []
    ids = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
    return ids

def translate_to_polish(text):
    translator = MyMemoryTranslator(source="pt-BR", target="pl-PL")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    translated = []
    for s in sentences:
        if len(s) < 3:
            continue
        try:
            # Respeitar limite de caracteres por bloco
            sub_chunks = [s[i:i+450] for i in range(0, len(s), 450)]
            sub_trans = [translator.translate(sc) for sc in sub_chunks]
            translated.append(" ".join(sub_trans))
        except Exception as e:
            logging.warning(f"Erro ao traduzir trecho '{s[:40]}...': {e}")
            translated.append(s)
        time.sleep(0.3)
    return " ".join(translated)

def process_video(video_id):
    logging.info(f"=== INICIANDO PROCESSAMENTO AUTÔNOMO: {video_id} ===")
    work_dir = WORKSPACE_DIR / video_id
    work_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Download do vídeo e thumbnail
    url = f"https://www.youtube.com/watch?v={video_id}"
    logging.info(f"Baixando mídia de {url}...")
    run_cmd([
        "yt-dlp",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "--output", str(work_dir / "original_video.%(ext)s"),
        url
    ])
    
    orig_video = work_dir / "original_video.mp4"
    orig_thumb = work_dir / "original_video.jpg"
    
    # 2. Obter título original
    meta_res = run_cmd(["yt-dlp", "--print", "%(title)s", url], check=False)
    orig_title = meta_res.stdout.strip() if meta_res.returncode == 0 else "Raport Wojskowy"
    
    # 3. Transcrição
    logging.info("Buscando transcrição via YouTubeTranscriptApi...")
    try:
        raw_trans = YouTubeTranscriptApi().fetch(video_id, languages=['pt', 'pt-BR'])
    except Exception as e:
        logging.warning(f"Transcrição em PT indisponível: {e}. Tentando listar...")
        trans_list = YouTubeTranscriptApi().list(video_id)
        raw_trans = trans_list.find_transcript(['pt', 'pt-BR', 'en']).fetch()
        
    transcript = [{'start': x.start, 'duration': x.duration, 'text': x.text} for x in raw_trans]
    with open(work_dir / "transcript.json", "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)
        
    # 4. Detecção de Patrocinador
    sponsor_kw = ["você europeu", "voce europeu", "inpi", "muvon", "cidadania portuguesa", "parceiro de hoje", "cupom"]
    sponsor_indices = []
    for i, item in enumerate(transcript):
        t_low = item["text"].lower()
        if any(kw in t_low for kw in sponsor_kw):
            sponsor_indices.append(i)
            
    sponsor_start = None
    sponsor_end = None
    if sponsor_indices:
        start_idx = max(0, sponsor_indices[0] - 1)
        end_idx = min(len(transcript) - 1, sponsor_indices[-1] + 1)
        sponsor_start = transcript[start_idx]["start"]
        sponsor_end = transcript[end_idx]["start"] + transcript[end_idx]["duration"]
        logging.info(f"Patrocinador detectado entre {sponsor_start:.2f}s e {sponsor_end:.2f}s")
        
    # 5. Corte do Vídeo (primeiros 3 segundos da vinheta + patrocinador se houver)
    clean_video = work_dir / "clean_video.mp4"
    if sponsor_start and sponsor_end and sponsor_start > 3.0:
        p1 = work_dir / "temp_p1.mp4"
        p2 = work_dir / "temp_p2.mp4"
        concat_txt = work_dir / "temp_concat.txt"
        
        run_cmd(["ffmpeg", "-y", "-ss", "00:00:03.00", "-to", str(sponsor_start), "-i", str(orig_video), "-c", "copy", str(p1)])
        run_cmd(["ffmpeg", "-y", "-ss", str(sponsor_end), "-i", str(orig_video), "-c", "copy", str(p2)])
        with open(concat_txt, "w") as f:
            f.write(f"file '{p1}'\nfile '{p2}'\n")
        run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(clean_video)])
        for f_rem in [p1, p2, concat_txt]:
            if f_rem.exists(): f_rem.unlink()
    else:
        run_cmd(["ffmpeg", "-y", "-ss", "00:00:03.00", "-i", str(orig_video), "-c", "copy", str(clean_video)])
        
    # 6. Geração do Roteiro Polonês
    logging.info("Adaptando roteiro para o polonês...")
    valid_text_segments = []
    for item in transcript:
        s = item["start"]
        if sponsor_start and sponsor_end and (sponsor_start <= s <= sponsor_end):
            continue
        # Limpar vinhetas e chamadas antigas
        t = item["text"]
        t = re.sub(r"Hoje no Mundo Militar", "Świat Militarny", t, flags=re.IGNORECASE)
        valid_text_segments.append(t)
        
    raw_pt_text = " ".join(valid_text_segments)
    polish_body = translate_to_polish(raw_pt_text)
    
    script_pl = f"Drodzy widzowie, witajcie na kanale Świat Militarny. Przed wami najnowszy raport wojenny i geopolityczny.\n\n{polish_body}\n\nJeśli materiał wam się podobał, zostawcie kciuk w górę i koniecznie zasubskrybujcie kanał Świat Militarny."
    script_file = work_dir / "script_pl.txt"
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(script_pl)
        
    # 7. Síntese de Voz Neural
    audio_file = work_dir / "audio_pl.mp3"
    logging.info("Sintetizando locução neural polonesa Marek...")
    run_cmd([
        str(VENV_EDGE_TTS),
        "--voice", "pl-PL-MarekNeural",
        "--rate=-12%",
        "--pitch=-4Hz",
        "-f", str(script_file),
        "--write-media", str(audio_file)
    ])
    
    # 8. Mux Final (0% áudio original + fade out)
    probe = run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_file)
    ])
    audio_duration = float(probe.stdout.strip())
    fade_start = max(0.0, audio_duration - 3.0)
    
    final_video = work_dir / "final_pl.mp4"
    logging.info(f"Renderizando vídeo final (duração: {audio_duration:.2f}s)...")
    run_cmd([
        "ffmpeg", "-y",
        "-i", str(clean_video),
        "-i", str(audio_file),
        "-filter_complex", f"[1:a]afade=t=out:st={fade_start:.2f}:d=3[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{audio_duration:.2f}",
        str(final_video)
    ])
    
    # 9. Título e Metadados
    logging.info("Preparando título e metadados em polonês...")
    title_translator = MyMemoryTranslator(source="pt-BR", target="pl-PL")
    try:
        clean_title_pt = re.sub(r"hoje no mundo militar", "Świat Militarny", orig_title, flags=re.IGNORECASE)
        title_pl = title_translator.translate(clean_title_pt)
    except Exception:
        title_pl = orig_title
        
    desc_pl = (
        f"{title_pl}\n\n"
        f"🔔 Subskrybuj Świat Militarny i włącz powiadomienia, aby śledzić codzienne raporty ze światowych frontów.\n\n"
        f"#wojna #geopolityka #nato #rosja #ukraina #militaria #wojsko #światmilitarny"
    )
    tags_pl = "wojna, geopolityka, nato, rosja, ukraina, militaria, wojsko, świat militarny, obronność, konflikt"
    
    # 10. Upload no YouTube (Público)
    logging.info("Enviando vídeo para o YouTube via API...")
    upload_cmd = [
        str(VENV_PYTHON),
        str(UPLOAD_SCRIPT),
        "--file", str(final_video),
        "--title", title_pl[:100],
        "--desc", desc_pl,
        "--tags", tags_pl,
        "--privacy", "public"
    ]
    if orig_thumb.exists():
        upload_cmd.extend(["--thumb", str(orig_thumb)])
        
    upload_res = run_cmd(upload_cmd, check=True)
    
    # Extrair URL gerada
    match = re.search(r"https://www.youtube.com/watch\?v=([\w-]+)", upload_res.stdout)
    published_url = match.group(0) if match else "URL não capturada"
    published_id = match.group(1) if match else ""
    
    # 11. Salvar ID no histórico
    save_processed_id(video_id)
    logging.info(f"[+] SUCESSO! Vídeo publicado: {published_url}")
    
    # 12. Notificar no Obsidian Vault
    if VAULT_SESSIONS_DIR.exists():
        now_str = datetime.now().strftime("%Y-%m-%d às %H:%M:%S")
        file_date = datetime.now().strftime("%Y-%m-%d")
        vault_note = VAULT_SESSIONS_DIR / f"{file_date} - Automação 24x7 Vídeo {video_id}.md"
        note_content = f"""---
tags:
  - sessao
  - ritmada
  - antigravity
  - automacao
data: {file_date}
hora: {datetime.now().strftime("%H:%M:%S")}
---

# 🤖 Automação 24/7: Novo Vídeo Publicado

**Data:** {now_str}

## Detalhes
- **Vídeo Origem:** https://www.youtube.com/watch?v={video_id} ({orig_title})
- **Vídeo Polonês:** {published_url}
- **Título PL:** {title_pl}
- **Status:** Publicado (Público)
- **Arquivo Renderizado:** `{final_video}`

---
*Publicado automaticamente pelo Daemon do Canal Świat Militarny.*
"""
        with open(vault_note, "w", encoding="utf-8") as f:
            f.write(note_content)
            
    return published_url

def main():
    logging.info("=== DAEMON CANAL POLONÊS INICIADO ===")
    logging.info(f"Canal Alvo: {TARGET_CHANNEL}")
    logging.info(f"Intervalo de Checagem: {CHECK_INTERVAL_SECONDS} segundos")
    
    while True:
        try:
            processed = load_processed_ids()
            latest_ids = get_latest_channel_video_ids(limit=3)
            logging.info(f"Últimos IDs encontrados no canal: {latest_ids}")
            
            for vid in reversed(latest_ids):
                if vid not in processed:
                    logging.info(f"NOVO VÍDEO DETECTADO: {vid}")
                    process_video(vid)
                else:
                    logging.info(f"Vídeo {vid} já processado anteriormente. Ignorando.")
                    
        except Exception as e:
            logging.error(f"Erro no loop do daemon: {e}", exc_info=True)
            
        logging.info(f"Aguardando {CHECK_INTERVAL_SECONDS // 60} minutos para a próxima verificação...")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
