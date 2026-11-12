#!/usr/bin/env python3
"""
Módulo de Geração e Publicação Automatizada de YouTube Shorts (9:16 Vertical)
Canal: Świat Militarny (@SwiatMilitarn)
"""

import os
import sys
import json
import re
import shutil
import subprocess
import logging
import asyncio
from pathlib import Path
from edge_tts import Communicate

BASE_DIR = Path(__file__).resolve().parent
SHORTS_PROCESSED_FILE = BASE_DIR / "processed_shorts.json"
UPLOAD_SCRIPT = BASE_DIR / "upload.py"
PYTHON_BIN = sys.executable

def find_binary(name):
    venv_bin = BASE_DIR / "venv" / "bin" / name
    if venv_bin.exists():
        return str(venv_bin)
    system_path = shutil.which(name)
    if system_path:
        return system_path
    return name

EDGE_TTS_BIN = find_binary("edge-tts")

def get_font_file():
    candidates = [
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def run_cmd(cmd, check=True):
    cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
    logging.info(f"Executando: {cmd_str}")
    res = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if check and res.returncode != 0:
        logging.error(f"Erro no comando:\nSTDERR: {res.stderr}\nSTDOUT: {res.stdout}")
        raise RuntimeError(f"Comando falhou: {cmd_str}")
    return res

def load_processed_shorts():
    if SHORTS_PROCESSED_FILE.exists():
        try:
            with open(SHORTS_PROCESSED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            logging.error(f"Erro ao ler {SHORTS_PROCESSED_FILE}: {e}")
    return set()

def save_processed_short(video_id):
    current = load_processed_shorts()
    current.add(video_id)
    with open(SHORTS_PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(current)), f, indent=2, ensure_ascii=False)
    logging.info(f"[+] Short para {video_id} salvo com sucesso em {SHORTS_PROCESSED_FILE}")

def create_short_pipeline(clean_video_path, title_pl, polish_body, work_dir, published_url="", video_id=None):
    """
    Renderiza e envia um YouTube Short vertical (9:16) de 30-50s a partir do vídeo limpo.
    """
    logging.info(f"=== INICIANDO GERAÇÃO DE SHORT: {title_pl} ===")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Extração do Gancho Principal (Hook)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", polish_body) if s.strip()]
    hook_sentences = []
    total_len = 0
    for s in sentences:
        if total_len + len(s) > 350 and hook_sentences:
            break
        hook_sentences.append(s)
        total_len += len(s)

    hook_text = " ".join(hook_sentences)
    if not hook_text:
        hook_text = title_pl

    short_script = (
        f"{hook_text}\n\n"
        f"Pełny raport i szczegóły analizy znajdziesz w najnowszym materiale na kanale Świat Militarny. "
        f"Zasubskrybuj kanał, aby nie przegapić."
    )

    script_file = work_dir / "short_script.txt"
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(short_script)

    # 2. Síntese de Voz Rápida para o Short (taxa +3% para dinamismo) com retentativas e timeout ampliado
    audio_short = work_dir / "short_audio.mp3"
    logging.info("Sintetizando locução do Short...")
    async def _synth_short():
        c = Communicate(
            text=short_script,
            voice="pl-PL-MarekNeural",
            rate="+3%",
            pitch="-2Hz",
            connect_timeout=60,
            receive_timeout=120
        )
        await c.save(str(audio_short))

    tts_success = False
    for attempt in range(4):
        try:
            asyncio.run(_synth_short())
            if audio_short.exists() and audio_short.stat().st_size > 0:
                tts_success = True
                break
        except Exception as e:
            logging.warning(f"Tentativa {attempt+1} de síntese do Short falhou: {e}. Aguardando...")
            time.sleep(3.0 * (attempt + 1))
    if not tts_success:
        raise RuntimeError(f"Falha definitiva ao sintetizar áudio para o Short: {audio_short}")

    # 3. Duração da Locução
    probe = run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_short)
    ])
    duration = float(probe.stdout.strip())
    # Limita entre 20s e 55s
    duration = min(max(duration, 20.0), 55.0)
    logging.info(f"Duração calculada para o Short: {duration:.2f}s")

    # 4. Preparação dos Textos do Layout Visual
    # Limpa caracteres e formata o título superior do Short
    clean_sub = re.sub(r"[-–—:]", " ", title_pl)
    words = clean_sub.split()
    short_headline = " ".join(words[:5]).upper() if words else "RAPORT WOJSKOWY"
    if len(short_headline) > 36:
        short_headline = short_headline[:36]

    h1_file = work_dir / "h1.txt"
    h2_file = work_dir / "h2.txt"
    h3_file = work_dir / "h3.txt"
    h4_file = work_dir / "h4.txt"

    with open(h1_file, "w", encoding="utf-8") as f:
        f.write("ŚWIAT MILITARNY")
    with open(h2_file, "w", encoding="utf-8") as f:
        f.write(short_headline)
    with open(h3_file, "w", encoding="utf-8") as f:
        f.write("PEŁNY RAPORT NA KANALE")
    with open(h4_file, "w", encoding="utf-8") as f:
        f.write("SUBSKRYBUJ")

    # 5. Renderização FFmpeg 9:16 Vertical com Blur e Textos
    font_file = get_font_file()
    font_arg = f":fontfile={font_file}" if font_file else ":font='DejaVu Sans:style=Bold'"

    filter_complex = (
        f"[0:v]scale=120:213,boxblur=2:1,scale=1080:1920:flags=bilinear,eq=brightness=-0.25[bg];"
        f"[0:v]scale=1080:-1[fg];"
        f"[bg][fg]overlay=0:(H-h)/2[base];"
        f"[base]drawtext={font_arg}:textfile='{h1_file}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=240:box=1:boxcolor=black@0.7:boxborderw=12,"
        f"drawtext={font_arg}:textfile='{h2_file}':fontcolor=yellow:fontsize=34:x=(w-text_w)/2:y=340:box=1:boxcolor=black@0.7:boxborderw=10,"
        f"drawtext={font_arg}:textfile='{h3_file}':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=1550:box=1:boxcolor=black@0.7:boxborderw=12,"
        f"drawtext={font_arg}:textfile='{h4_file}':fontcolor=red:fontsize=44:x=(w-text_w)/2:y=1640:box=1:boxcolor=white@0.9:boxborderw=12,"
        f"setsar=1,format=yuv420p[v]"
    )

    short_video = work_dir / "short_pl.mp4"
    fade_start = max(0.0, duration - 1.5)

    logging.info("Renderizando Short vertical 9:16...")
    run_cmd([
        "ffmpeg", "-y",
        "-i", str(clean_video_path),
        "-i", str(audio_short),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.2f}",
        str(short_video)
    ])

    # 6. Publicação no YouTube via upload.py
    short_title = f"{title_pl[:80]} #Shorts"
    short_desc = (
        f"{title_pl}\n\n"
        f"👉 Obejrzyj pełną analizę na kanale: {published_url}\n\n"
        f"🔔 Zasubskrybuj Świat Militarny i bądź na bieżąco!\n\n"
        f"#Shorts #wojna #geopolityka #militaria #wojsko #światmilitarny"
    )
    short_tags = "shorts, wojna, geopolityka, militaria, wojsko, świat militarny, konflikt, obronność"

    logging.info("Enviando Short para o YouTube...")
    upload_cmd = [
        PYTHON_BIN,
        str(UPLOAD_SCRIPT),
        "--file", str(short_video),
        "--title", short_title,
        "--desc", short_desc,
        "--tags", short_tags,
        "--privacy", "public"
    ]
    upload_res = run_cmd(upload_cmd, check=True)

    match = re.search(r"https://www.youtube.com/watch\?v=([\w-]+)", upload_res.stdout)
    short_url = match.group(0) if match else "URL não capturada"
    logging.info(f"[+] SUCESSO! Short publicado: {short_url}")

    if video_id:
        save_processed_short(video_id)

    return short_url

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Uso: python generate_short.py <clean_video_path> <title_pl> <polish_body> [published_url] [video_id]")
        sys.exit(1)
    
    clean_v = sys.argv[1]
    title = sys.argv[2]
    body = sys.argv[3]
    pub_url = sys.argv[4] if len(sys.argv) > 4 else ""
    vid_id = sys.argv[5] if len(sys.argv) > 5 else None
    
    out_dir = BASE_DIR / "workspace" / f"short_{vid_id or 'manual'}"
    url = create_short_pipeline(clean_v, title, body, out_dir, pub_url, vid_id)
    print(f"Short URL: {url}")
