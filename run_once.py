#!/usr/bin/env python3
"""
Pipeline de Execução Única (Run-Once) - Canal 'Świat Militarny'
Projetado para execução agendada no GitHub Actions ou runners remotos.
1. Checa os vídeos mais recentes de @hojenomundomilitar.
2. Identifica se há vídeo inédito em relação a processed_ids.json.
3. Se houver, processa exatamente 1 vídeo inédito:
   - Download (720p) + thumbnail
   - Transcrição via YouTubeTranscriptApi
   - Detecção e corte de patrocinador
   - Corte de abertura (primeiros 3s)
   - Tradução do roteiro para polonês
   - Síntese vocal neural com edge-tts (pl-PL-MarekNeural)
   - Mux e renderização FFmpeg
   - Upload via YouTube Data API v3 (público)
   - Atualização de processed_ids.json
4. Se não houver novos vídeos, finaliza com status 0.
"""

import os
import sys
import time
import json
import re
import shutil
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi
from deep_translator import MyMemoryTranslator

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
PROCESSED_FILE = BASE_DIR / "processed_ids.json"
UPLOAD_SCRIPT = BASE_DIR / "upload.py"
TOKEN_FILE = BASE_DIR / "token.json"
COOKIES_FILE = BASE_DIR / "cookies.txt"

TARGET_CHANNEL = "https://www.youtube.com/@hojenomundomilitar/videos"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

def find_binary(name):
    # Procura no PATH do sistema ou no venv local se existir
    venv_bin = BASE_DIR / "venv" / "bin" / name
    if venv_bin.exists():
        return str(venv_bin)
    system_path = shutil.which(name)
    if system_path:
        return system_path
    return name

EDGE_TTS_BIN = find_binary("edge-tts")
PYTHON_BIN = sys.executable

def get_ytdlp_cmd():
    ytdlp = find_binary("yt-dlp")
    cmd = [ytdlp, "--remote-components", "ejs:github"]
    deno_bin = shutil.which("deno")
    node_bin = shutil.which("node")
    if deno_bin:
        cmd.extend(["--js-runtimes", f"deno:{deno_bin}"])
    elif node_bin:
        cmd.extend(["--js-runtimes", f"node:{node_bin}"])
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    return cmd

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
        json.dump(sorted(list(current)), f, indent=2, ensure_ascii=False)
    logging.info(f"[+] ID {video_id} salvo com sucesso em {PROCESSED_FILE}")

def get_latest_channel_video_ids(limit=5):
    cmd = get_ytdlp_cmd() + ["--flat-playlist", "--playlist-end", str(limit), "--print", "%(id)s", TARGET_CHANNEL]
    res = run_cmd(cmd, check=False)
    if res.returncode != 0:
        logging.warning("Falha ao checar canal com yt-dlp")
        return []
    ids = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
    return ids

def fetch_transcript(video_id, work_dir):
    """
    Obtém a transcrição em português com fallback entre yt-dlp (autenticado) e YouTubeTranscriptApi.
    """
    sub_prefix = work_dir / "subtitles"
    cmd = get_ytdlp_cmd() + [
        "--write-auto-subs", "--write-subs",
        "--sub-format", "json3",
        "--sub-lang", "pt,pt-BR",
        "--skip-download",
        "-o", f"{sub_prefix}.%(ext)s",
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    try:
        run_cmd(cmd, check=False)
        for cand in [work_dir / "subtitles.pt.json3", work_dir / "subtitles.pt-BR.json3"]:
            if cand.exists():
                with open(cand, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = []
                for ev in data.get("events", []):
                    start = ev.get("tStartMs", 0) / 1000.0
                    duration = ev.get("dDurationMs", 0) / 1000.0
                    text = "".join([s.get("utf8", "") for s in ev.get("segs", [])]).strip()
                    if text and text != "\n":
                        items.append({"start": start, "duration": duration, "text": text})
                if items:
                    logging.info(f"Transcrição obtida com sucesso via yt-dlp json3 ({len(items)} blocos)")
                    return items
    except Exception as e:
        logging.warning(f"yt-dlp subtitle download falhou: {e}")

    try:
        logging.info("Tentando YouTubeTranscriptApi como fallback...")
        raw_trans = YouTubeTranscriptApi().fetch(video_id, languages=['pt', 'pt-BR'])
        return [{'start': x.start, 'duration': x.duration, 'text': x.text} for x in raw_trans]
    except Exception as e:
        logging.warning(f"Transcrição em PT direta indisponível: {e}. Listando faixas...")
        trans_list = YouTubeTranscriptApi().list(video_id)
        raw_trans = trans_list.find_transcript(['pt', 'pt-BR', 'en']).fetch()
        return [{'start': x.start, 'duration': x.duration, 'text': x.text} for x in raw_trans]

def split_into_safe_chunks(text, max_chars=380):
    raw_units = re.split(r"(?<=[.!?,;:])\s+", text)
    units = []
    for u in raw_units:
        u = u.strip()
        if not u:
            continue
        if len(u) > max_chars:
            words = u.split()
            cur = []
            cur_l = 0
            for w in words:
                if cur_l + len(w) + 1 > max_chars and cur:
                    units.append(" ".join(cur))
                    cur = [w]
                    cur_l = len(w)
                else:
                    cur.append(w)
                    cur_l += len(w) + 1
            if cur:
                units.append(" ".join(cur))
        else:
            units.append(u)

    chunks = []
    cur_chunk = []
    cur_len = 0
    for u in units:
        if cur_len + len(u) + 1 > max_chars and cur_chunk:
            chunks.append(" ".join(cur_chunk))
            cur_chunk = [u]
            cur_len = len(u)
        else:
            cur_chunk.append(u)
            cur_len += len(u) + 1
    if cur_chunk:
        chunks.append(" ".join(cur_chunk))
    return chunks

def translate_to_polish(text):
    translator = MyMemoryTranslator(source="pt-BR", target="pl-PL", email="swiatmilitarny@gmail.com")
    chunks = split_into_safe_chunks(text, max_chars=380)

    logging.info(f"Traduzindo {len(chunks)} blocos consolidados para polonês...")
    translated = []
    for i, c in enumerate(chunks):
        chunk_success = False
        for attempt in range(4):
            try:
                res = translator.translate(c)
                if res and res != c:
                    translated.append(res)
                    chunk_success = True
                    break
            except Exception as e:
                logging.warning(f"Tentativa {attempt+1} falhou para bloco {i+1} ({len(c)} chars): {e}")
                time.sleep(1.0 * (attempt + 1))
        if not chunk_success:
            # Fallback: divide o bloco ao meio
            words = c.split()
            mid = len(words) // 2
            sub_c1, sub_c2 = " ".join(words[:mid]), " ".join(words[mid:])
            try:
                res1 = translator.translate(sub_c1) if sub_c1 else ""
                res2 = translator.translate(sub_c2) if sub_c2 else ""
                translated.append(f"{res1} {res2}".strip())
                chunk_success = True
            except Exception as e2:
                logging.error(f"Falha definitiva ao traduzir bloco {i+1}: {e2}. Mantendo original.")
                translated.append(c)
        time.sleep(0.4)

    return " ".join(translated)

def process_video(video_id):
    logging.info(f"=== INICIANDO PROCESSAMENTO: {video_id} ===")
    work_dir = WORKSPACE_DIR / video_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. Download do vídeo e thumbnail
        logging.info(f"Baixando mídia de {url}...")
        dl_cmd = get_ytdlp_cmd() + [
            "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "--merge-output-format", "mp4",
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "--output", str(work_dir / "original_video.%(ext)s"),
            url
        ]
        run_cmd(dl_cmd)

        orig_video = work_dir / "original_video.mp4"
        orig_thumb = work_dir / "original_video.jpg"

        # 2. Obter título original
        meta_cmd = get_ytdlp_cmd() + ["--print", "%(title)s", url]
        meta_res = run_cmd(meta_cmd, check=False)
        orig_title = meta_res.stdout.strip() if meta_res.returncode == 0 else "Raport Wojskowy"

        # 3. Transcrição
        logging.info("Buscando transcrição...")
        transcript = fetch_transcript(video_id, work_dir)
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

        # 5. Corte de Vinheta (primeiros 3 segundos exatos) + Patrocinador se houver
        clean_video = work_dir / "clean_video.mp4"
        if sponsor_start and sponsor_end and sponsor_start > 3.0:
            p1 = work_dir / "temp_p1.mp4"
            p2 = work_dir / "temp_p2.mp4"
            concat_txt = work_dir / "temp_concat.txt"

            # Re-encoding garante corte exato no frame sem herdar keyframe anterior do logo
            run_cmd([
                "ffmpeg", "-y",
                "-i", str(orig_video),
                "-ss", "00:00:03.00",
                "-to", str(sponsor_start),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-an", str(p1)
            ])
            run_cmd([
                "ffmpeg", "-y",
                "-i", str(orig_video),
                "-ss", str(sponsor_end),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-an", str(p2)
            ])
            with open(concat_txt, "w") as f:
                f.write(f"file '{p1}'\nfile '{p2}'\n")
            run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(clean_video)])
            for f_rem in [p1, p2, concat_txt]:
                if f_rem.exists():
                    f_rem.unlink()
        else:
            run_cmd([
                "ffmpeg", "-y",
                "-i", str(orig_video),
                "-ss", "00:00:03.00",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-an", str(clean_video)
            ])

        # 6. Adaptação do Roteiro para Polonês
        logging.info("Adaptando roteiro para o polonês...")
        valid_text_segments = []
        for item in transcript:
            s = item["start"]
            if sponsor_start and sponsor_end and (sponsor_start <= s <= sponsor_end):
                continue
            t = item["text"]
            t = re.sub(r"Hoje no Mundo Militar", "Świat Militarny", t, flags=re.IGNORECASE)
            valid_text_segments.append(t)

        raw_pt_text = " ".join(valid_text_segments)
        polish_body = translate_to_polish(raw_pt_text)

        script_pl = (
            f"Drodzy widzowie, witajcie na kanale Świat Militarny. Przed wami najnowszy raport wojenny i geopolityczny.\n\n"
            f"{polish_body}\n\n"
            f"Jeśli materiał wam się podobał, zostawcie kciuk w górę i koniecznie zasubskrybujcie kanał Świat Militarny."
        )
        script_file = work_dir / "script_pl.txt"
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(script_pl)

        # 7. Síntese de Voz Neural Marek
        audio_file = work_dir / "audio_pl.mp3"
        logging.info("Sintetizando locução neural polonesa Marek...")
        run_cmd([
            EDGE_TTS_BIN,
            "--voice", "pl-PL-MarekNeural",
            "--rate=-12%",
            "--pitch=-4Hz",
            "-f", str(script_file),
            "--write-media", str(audio_file)
        ])

        # 8. Mux Final (0% áudio original, 100% locução polonesa com fade-out de 3s)
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
        logging.info("Traduzindo título e metadados para polonês...")
        clean_title_pt = re.sub(r"hoje no mundo militar", "Świat Militarny", orig_title, flags=re.IGNORECASE)
        title_pl = translate_to_polish(clean_title_pt)
        if not title_pl or title_pl == clean_title_pt:
            try:
                title_translator = MyMemoryTranslator(source="pt-BR", target="pl-PL", email="swiatmilitarny@gmail.com")
                title_pl = title_translator.translate(clean_title_pt)
            except Exception as e:
                logging.error(f"Erro ao traduzir título: {e}")
                title_pl = title_pl or clean_title_pt

        desc_pl = (
            f"{title_pl}\n\n"
            f"🔔 Subskrybuj Świat Militarny i włącz powiadomienia, aby śledzić codzienne raporty ze światowych frontów.\n\n"
            f"#wojna #geopolityka #nato #rosja #ukraina #militaria #wojsko #światmilitarny"
        )
        tags_pl = "wojna, geopolityka, nato, rosja, ukraina, militaria, wojsko, świat militarny, obronność, konflikt"

        # 10. Upload no YouTube via API
        logging.info("Enviando vídeo para o YouTube via API...")
        upload_cmd = [
            PYTHON_BIN,
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

        match = re.search(r"https://www.youtube.com/watch\?v=([\w-]+)", upload_res.stdout)
        published_url = match.group(0) if match else "URL não capturada"
        logging.info(f"[+] SUCESSO! Vídeo publicado: {published_url}")

        # 11. Geração e Publicação Automática de YouTube Short (9:16)
        try:
            from generate_short import create_short_pipeline
            short_url = create_short_pipeline(
                clean_video_path=clean_video,
                title_pl=title_pl,
                polish_body=polish_body,
                work_dir=work_dir / "short_gen",
                published_url=published_url,
                video_id=video_id
            )
            logging.info(f"[+] SUCESSO! Short publicado: {short_url}")
        except Exception as e:
            logging.error(f"[!] Falha ao gerar/publicar Short (vídeo principal preservado): {e}")

        # 12. Salvar ID no histórico permanente
        save_processed_id(video_id)

    finally:
        # Limpeza do workspace para economizar espaço
        if work_dir.exists():
            try:
                shutil.rmtree(work_dir)
                logging.info(f"Workspace limpo: {work_dir}")
            except Exception as e:
                logging.warning(f"Erro ao limpar workspace: {e}")

def main():
    logging.info("=== RUN-ONCE PIPELINE - SWIAT MILITARNY ===")
    processed = load_processed_ids()
    latest_ids = get_latest_channel_video_ids(limit=5)
    logging.info(f"Últimos IDs detectados no canal: {latest_ids}")
    logging.info(f"Total já processados: {len(processed)}")

    unprocessed = [vid for vid in reversed(latest_ids) if vid not in processed]
    if not unprocessed:
        logging.info("Nenhum vídeo inédito encontrado. Pipeline finalizado com sucesso.")
        sys.exit(0)

    # Processa 1 vídeo por execução de workflow
    target_vid = unprocessed[0]
    logging.info(f"Processando próximo vídeo inédito da fila: {target_vid}")
    process_video(target_vid)
    logging.info("Pipeline concluído com sucesso!")

if __name__ == "__main__":
    main()
