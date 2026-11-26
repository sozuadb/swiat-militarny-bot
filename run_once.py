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
import asyncio
from datetime import datetime
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from deep_translator import MyMemoryTranslator
from edge_tts import Communicate

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

def synthesize_polish_speech(text, output_file, rate="-12%", pitch="-4Hz", voice="pl-PL-MarekNeural"):
    async def _synth():
        c = Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            connect_timeout=60,
            receive_timeout=180
        )
        await c.save(str(output_file))

    for attempt in range(4):
        try:
            asyncio.run(_synth())
            if Path(output_file).exists() and Path(output_file).stat().st_size > 0:
                return True
        except Exception as e:
            logging.warning(f"Tentativa {attempt+1} de síntese de voz falhou: {e}. Aguardando...")
            time.sleep(3.0 * (attempt + 1))
    return False

def has_valid_auth_cookies(cookie_path):
    if not cookie_path.exists():
        return False
    try:
        txt = cookie_path.read_text(encoding="utf-8", errors="ignore")
        return any(f"\t{k}\t" in txt for k in ("SID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO"))
    except Exception:
        return False

def get_ytdlp_cmd(use_cookies=True, clients="mweb,android_vr,ios,android,web"):
    ytdlp = find_binary("yt-dlp")
    cmd = [
        ytdlp,
        "--remote-components", "ejs:github",
        "--extractor-args", f"youtube:player_client={clients};lang=pt",
        "--extractor-args", "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416"
    ]
    deno_bin = shutil.which("deno")
    node_bin = shutil.which("node")
    if deno_bin:
        cmd.extend(["--js-runtimes", f"deno:{deno_bin}"])
    elif node_bin:
        cmd.extend(["--js-runtimes", f"node:{node_bin}"])
    ytdlp_proxy = os.environ.get("YTDLP_PROXY", "").strip()
    if ytdlp_proxy:
        cmd.extend(["--proxy", ytdlp_proxy])
    if use_cookies and has_valid_auth_cookies(COOKIES_FILE):
        # Copia para arquivo efêmero para evitar que yt-dlp sobrescreva/expire cookies.txt
        tmp_cookies = WORKSPACE_DIR / "runtime_cookies.txt"
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(COOKIES_FILE, tmp_cookies)
        cmd.extend(["--cookies", str(tmp_cookies)])
    return cmd

def run_cmd(cmd, check=True):
    cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
    logging.info(f"Executando: {cmd_str}")
    res = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if check and res.returncode != 0:
        logging.error(f"Erro no comando:\nSTDERR: {res.stderr}\nSTDOUT: {res.stdout}")
        raise RuntimeError(f"Comando falhou: {cmd_str}\n{res.stderr[-500:]}")
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

    # Sincronização automática com GitHub para manter runner da nuvem ciente
    try:
        subprocess.run(["git", "add", "processed_ids.json", "processed_shorts.json"], cwd=BASE_DIR, capture_output=True)
        commit_res = subprocess.run(["git", "commit", "-m", f"auto: registrar {video_id} [skip ci]"], cwd=BASE_DIR, capture_output=True)
        if commit_res.returncode == 0:
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=BASE_DIR, capture_output=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=BASE_DIR, capture_output=True)
            logging.info(f"[+] Sincronizado com GitHub remoto: {video_id}")
    except Exception as e:
        logging.warning(f"Aviso: falha no auto-git push: {e}")

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
    Obtém a transcrição em português com 3 camadas de redundância:
    1. yt-dlp json3 (cliente web + impersonate chrome)
    2. YouTubeTranscriptApi (via proxy WARP)
    3. faster-whisper ASR local direto no original_video.mp4 (100% imune a bloqueio de IP)
    """
    sub_prefix = work_dir / "subtitles"
    cmd = get_ytdlp_cmd(clients="web,mweb") + [
        "--impersonate", "chrome",
        "--write-auto-subs", "--write-subs",
        "--sub-format", "json3",
        "--sub-langs", "pt.*,pt,pt-BR",
        "--skip-download",
        "-o", f"{sub_prefix}.%(ext)s",
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    try:
        run_cmd(cmd, check=False)
        cands = [work_dir / "subtitles.pt.json3", work_dir / "subtitles.pt-BR.json3", work_dir / "subtitles.pt-orig.json3"]
        for extra in sorted(work_dir.glob("subtitles*.json3")):
            if extra not in cands:
                cands.append(extra)
        for cand in cands:
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
                    logging.info(f"Transcrição obtida com sucesso via yt-dlp json3 ({cand.name}: {len(items)} blocos)")
                    return items
    except Exception as e:
        logging.warning(f"yt-dlp subtitle download falhou: {e}")

    ytdlp_proxy = os.environ.get("YTDLP_PROXY", "").strip()
    proxy_cfg = GenericProxyConfig(http_url=ytdlp_proxy, https_url=ytdlp_proxy) if ytdlp_proxy else None
    ytt_api = YouTubeTranscriptApi(proxy_config=proxy_cfg) if proxy_cfg else YouTubeTranscriptApi()

    try:
        logging.info("Tentando YouTubeTranscriptApi como fallback...")
        raw_trans = ytt_api.fetch(video_id, languages=['pt', 'pt-BR', 'pt-orig'])
        return [{'start': x.start, 'duration': x.duration, 'text': x.text} for x in raw_trans]
    except Exception as e:
        logging.warning(f"YouTubeTranscriptApi direta indisponível ({type(e).__name__}). Tentando listagem...")
        try:
            trans_list = ytt_api.list(video_id)
            raw_trans = trans_list.find_transcript(['pt', 'pt-BR', 'pt-orig', 'en']).fetch()
            return [{'start': x.start, 'duration': x.duration, 'text': x.text} for x in raw_trans]
        except Exception as e2:
            logging.warning(f"API de legendas bloqueada no IP da nuvem ({type(e2).__name__}). Acionando faster-whisper local no áudio baixado...")

    orig_video = work_dir / "original_video.mp4"
    if not orig_video.exists():
        raise RuntimeError(f"Áudio/vídeo {orig_video} não encontrado para transcrição offline.")

    from faster_whisper import WhisperModel
    wav_16k = work_dir / "asr_16k.wav"
    run_cmd([
        find_binary("ffmpeg"), "-y", "-i", str(orig_video),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_16k)
    ])
    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    segments, _ = model.transcribe(str(wav_16k), language="pt", vad_filter=True)
    items = []
    for seg in segments:
        txt = seg.text.strip()
        if txt:
            items.append({
                "start": round(float(seg.start), 3),
                "duration": round(max(0.1, float(seg.end - seg.start)), 3),
                "text": txt
            })
    wav_16k.unlink(missing_ok=True)
    if not items:
        raise RuntimeError("faster-whisper não retornou segmentos de fala.")
    logging.info(f"[+] Transcrição offline via faster-whisper concluída ({len(items)} blocos)!")
    return items

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

def rotate_warp_proxy():
    """Rotaciona identidade do Cloudflare WARP caso um IP específico de saída seja bloqueado."""
    warp_bin = shutil.which("warp-cli")
    if not warp_bin or not os.environ.get("YTDLP_PROXY"):
        return False
    logging.info("Rotacionando identidade Cloudflare WARP para novo IP de saída...")
    cmds = [
        [warp_bin, "--accept-tos", "disconnect"],
        [warp_bin, "--accept-tos", "registration", "delete"],
        [warp_bin, "--accept-tos", "registration", "new"],
        [warp_bin, "--accept-tos", "mode", "proxy"],
        [warp_bin, "--accept-tos", "proxy", "port", "40000"],
        [warp_bin, "--accept-tos", "connect"],
    ]
    for c in cmds:
        subprocess.run(c, capture_output=True)
        time.sleep(0.5)
    for _ in range(15):
        chk = subprocess.run(
            ["curl", "-sf", "--socks5-hostname", "127.0.0.1:40000", "https://cloudflare.com/cdn-cgi/trace"],
            capture_output=True, text=True
        )
        if "warp=on" in chk.stdout:
            logging.info(f"Novo túnel WARP ativo: {[l for l in chk.stdout.splitlines() if l.startswith(('ip=', 'colo='))]}")
            return True
        time.sleep(1.0)
    return False

def download_video_resilient(url, work_dir):
    dl_args = [
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "--output", str(work_dir / "original_video.%(ext)s"),
        url
    ]
    ip_modes = [[], ["--force-ipv4"]] if os.environ.get("YTDLP_PROXY") else [[]]
    max_rounds = 8 if os.environ.get("YTDLP_PROXY") else 2
    last_err = None
    for rnd in range(max_rounds):
        for ip_flag in ip_modes:
            try:
                run_cmd(get_ytdlp_cmd(use_cookies=True, clients="mweb,android_vr,ios,android,web") + ip_flag + dl_args)
                if (work_dir / "original_video.mp4").exists():
                    size_mb = (work_dir / "original_video.mp4").stat().st_size / (1024 * 1024)
                    logging.info(f"[+] SUCESSO DOWNLOAD MP4 ({size_mb:.2f} MB) na rodada {rnd+1} ({ip_flag or 'default'})")
                    return
            except Exception as e:
                last_err = e
                logging.warning(f"Tentativa rodada {rnd+1} ({ip_flag}) falhou.")
        if rnd + 1 < max_rounds:
            rotate_warp_proxy()
    raise last_err or RuntimeError("Todos os IPs/perfis de download falharam.")

def process_video(video_id):
    logging.info(f"=== INICIANDO PROCESSAMENTO: {video_id} ===")
    work_dir = WORKSPACE_DIR / video_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 1. Download do vídeo e thumbnail (resiliente com rotação WARP IPv4/IPv6)
        logging.info(f"Baixando mídia de {url}...")
        download_video_resilient(url, work_dir)

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
        tts_ok = synthesize_polish_speech(script_pl, audio_file, rate="-12%", pitch="-4Hz")

        if not tts_ok:
            logging.info("Tentando síntese particionada em blocos para evitar timeout do websocket...")
            paragraphs = [p.strip() for p in script_pl.split("\n\n") if p.strip()]
            part_files = []
            for idx, p in enumerate(paragraphs):
                p_audio = work_dir / f"audio_part_{idx:02d}.mp3"
                p_ok = synthesize_polish_speech(p, p_audio, rate="-12%", pitch="-4Hz")
                if not p_ok:
                    raise RuntimeError(f"Falha definitiva ao sintetizar parte {idx}")
                part_files.append(p_audio)
                time.sleep(0.5)

            concat_list = work_dir / "audio_concat.txt"
            with open(concat_list, "w", encoding="utf-8") as cf:
                for pf in part_files:
                    cf.write(f"file '{pf.resolve()}'\n")
            run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(audio_file)])
            if audio_file.exists() and audio_file.stat().st_size > 0:
                tts_ok = True

        if not tts_ok:
            raise RuntimeError(f"Falha definitiva ao sintetizar áudio para o vídeo principal: {audio_file}")

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

        # 9.1 Geração de Thumbnail Localizada em Polonês
        thumb_to_upload = orig_thumb
        localized_thumb = work_dir / "thumbnail_pl.jpg"
        try:
            from thumbnail_generator import generate_localized_thumbnail
            if orig_thumb.exists() and generate_localized_thumbnail(orig_thumb, title_pl, localized_thumb):
                thumb_to_upload = localized_thumb
                logging.info(f"[+] Thumbnail localizada em polonês pronta: {thumb_to_upload}")
        except Exception as e:
            logging.warning(f"Falha ao gerar thumbnail localizada, usando original: {e}")

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
        if thumb_to_upload.exists():
            upload_cmd.extend(["--thumb", str(thumb_to_upload)])

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

def test_cloud_download(video_id):
    logging.info(f"=== TESTE DE DOWNLOAD REAL EM NUVEM: {video_id} ===")
    work_dir = WORKSPACE_DIR / f"test_{video_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        download_video_resilient(url, work_dir)
        transcript = fetch_transcript(video_id, work_dir)
        logging.info(f"[+] SUCESSO TRANSCRIÇÃO EM NUVEM: {len(transcript)} blocos obtidos! Amostra: {transcript[0]['text'][:80]}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

def main():
    logging.info("=== RUN-ONCE PIPELINE - SWIAT MILITARNY ===")
    if len(sys.argv) >= 3 and sys.argv[1] == "--test-download":
        test_cloud_download(sys.argv[2])
        sys.exit(0)
    processed = load_processed_ids()
    latest_ids = get_latest_channel_video_ids(limit=10)
    logging.info(f"Últimos IDs detectados no canal: {latest_ids}")
    logging.info(f"Total já processados: {len(processed)}")

    unprocessed = [vid for vid in reversed(latest_ids) if vid not in processed]
    if not unprocessed:
        logging.info("Nenhum vídeo inédito encontrado. Pipeline finalizado com sucesso.")
        sys.exit(0)

    logging.info(f"Fila de vídeos inéditos detectada ({len(unprocessed)}): {unprocessed}")
    for idx, target_vid in enumerate(unprocessed, 1):
        logging.info(f"=== [{idx}/{len(unprocessed)}] Processando vídeo inédito da fila: {target_vid} ===")
        try:
            process_video(target_vid)
        except Exception as e:
            err_msg = str(e)
            if "quotaExceeded" in err_msg or "uploadLimitExceeded" in err_msg or "429" in err_msg:
                logging.warning(f"Cota/limite de upload atingido em {target_vid}. Encerrando fila com segurança para preservar commits anteriores.")
                break
            logging.error(f"Falha ao processar {target_vid}: {e}", exc_info=True)
            if idx == len(unprocessed) and idx == 1:
                raise
    logging.info("Pipeline concluído com sucesso!")

if __name__ == "__main__":
    main()
