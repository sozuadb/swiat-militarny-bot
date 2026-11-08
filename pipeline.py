#!/usr/bin/env python3
"""
Pipeline de Clonagem e Dublagem Automatizada para o Canal 'Świat Militarny'
Autor: Ritmada
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
VENV_EDGE_TTS = BASE_DIR / "venv" / "bin" / "edge-tts"
UPLOAD_SCRIPT = BASE_DIR / "upload.py"
WORKSPACE_DIR = BASE_DIR / "workspace"

def run_cmd(cmd, check=True):
    print(f"[*] Executando: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    res = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"[-] Erro ao executar comando:\nSTDERR: {res.stderr}\nSTDOUT: {res.stdout}")
        sys.exit(1)
    return res

def download_video(url, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    video_template = str(out_dir / "original_video.%(ext)s")
    
    cmd = [
        "yt-dlp",
        "--format", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "--write-sub",
        "--write-auto-sub",
        "--sub-lang", "pt",
        "--sub-format", "vtt",
        "--output", video_template,
        "--print-json",
        url
    ]
    res = run_cmd(cmd)
    
    # Encontrar arquivo de metadados
    meta = None
    try:
        meta = json.loads(res.stdout.strip().split("\n")[-1])
    except Exception:
        pass
    
    video_path = out_dir / "original_video.mp4"
    thumb_path = out_dir / "original_video.jpg"
    sub_path = out_dir / "original_video.pt.vtt"
    
    return {
        "video_path": video_path,
        "thumb_path": thumb_path if thumb_path.exists() else None,
        "sub_path": sub_path if sub_path.exists() else None,
        "meta": meta
    }

def cut_and_clean_video(in_video, out_video, start_cut=5.0, sponsor_start=None, sponsor_end=None):
    """
    Corta os primeiros X segundos (vinheta) e o intervalo de patrocínio (se fornecido).
    """
    in_video = str(in_video)
    out_video = str(out_video)
    work_dir = Path(in_video).parent
    
    if sponsor_start is not None and sponsor_end is not None:
        p1 = str(work_dir / "temp_p1.mp4")
        p2 = str(work_dir / "temp_p2.mp4")
        concat_txt = str(work_dir / "temp_concat.txt")
        
        # P1: start_cut até sponsor_start
        run_cmd([
            "ffmpeg", "-y", "-ss", str(start_cut), "-to", str(sponsor_start),
            "-i", in_video, "-c", "copy", p1
        ])
        
        # P2: sponsor_end até o final
        run_cmd([
            "ffmpeg", "-y", "-ss", str(sponsor_end),
            "-i", in_video, "-c", "copy", p2
        ])
        
        with open(concat_txt, "w") as f:
            f.write(f"file '{p1}'\nfile '{p2}'\n")
            
        run_cmd([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_txt, "-c", "copy", out_video
        ])
        
        # Cleanup
        for f in [p1, p2, concat_txt]:
            if os.path.exists(f):
                os.remove(f)
    else:
        # Apenas remove os primeiros start_cut segundos
        run_cmd([
            "ffmpeg", "-y", "-ss", str(start_cut),
            "-i", in_video, "-c", "copy", out_video
        ])
        
    return out_video

def generate_polish_audio(script_text_or_file, out_audio, rate="-12%", pitch="-4Hz"):
    """
    Gera áudio neural em polonês usando edge-tts.
    """
    out_audio = str(out_audio)
    if os.path.isfile(str(script_text_or_file)):
        cmd = [
            str(VENV_EDGE_TTS),
            "--voice", "pl-PL-MarekNeural",
            f"--rate={rate}",
            f"--pitch={pitch}",
            "-f", str(script_text_or_file),
            "--write-media", out_audio
        ]
    else:
        cmd = [
            str(VENV_EDGE_TTS),
            "--voice", "pl-PL-MarekNeural",
            f"--rate={rate}",
            f"--pitch={pitch}",
            "--text", str(script_text_or_file),
            "--write-media", out_audio
        ]
    run_cmd(cmd)
    return out_audio

def mux_final(clean_video, audio_path, out_final):
    """
    Combina o vídeo cortado com o áudio neural polonês, descartando 100% do áudio original
    e aplicando fade-out suave nos últimos 3 segundos.
    """
    clean_video = str(clean_video)
    audio_path = str(audio_path)
    out_final = str(out_final)
    
    # Obter duração do áudio gerado
    probe = run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ])
    duration = float(probe.stdout.strip())
    fade_start = max(0.0, duration - 3.0)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", clean_video,
        "-i", audio_path,
        "-filter_complex",
        f"[1:a]afade=t=out:st={fade_start:.2f}:d=3[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.2f}",
        out_final
    ]
    run_cmd(cmd)
    return out_final

def upload_to_youtube(video_path, title, description, tags, privacy="unlisted", thumbnail=None):
    cmd = [
        str(VENV_PYTHON),
        str(UPLOAD_SCRIPT),
        "--file", str(video_path),
        "--title", title,
        "--desc", description,
        "--tags", tags,
        "--privacy", privacy
    ]
    if thumbnail and os.path.exists(str(thumbnail)):
        cmd.extend(["--thumb", str(thumbnail)])
    
    res = run_cmd(cmd)
    return res.stdout

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline Świat Militarny")
    parser.add_argument("--url", required=True, help="URL do vídeo original do Hoje no Mundo Militar")
    parser.add_argument("--slug", default=None, help="Nome da pasta no workspace")
    parser.add_argument("--sponsor-start", type=float, default=None, help="Início do patrocinador em segundos")
    parser.add_argument("--sponsor-end", type=float, default=None, help="Fim do patrocinador em segundos")
    parser.add_argument("--script", default=None, help="Caminho do script polonês já adaptado")
    parser.add_argument("--title", default=None, help="Título em polonês para publicação")
    parser.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"])
    
    args = parser.parse_args()
    slug = args.slug or args.url.split("v=")[-1].split("&")[0]
    target_dir = WORKSPACE_DIR / slug
    
    print(f"[*] Iniciando ingestão do vídeo {args.url} em {target_dir}")
    info = download_video(args.url, target_dir)
    print(f"[+] Download concluído: {info['video_path']}")
    
    clean_video = target_dir / "clean_video.mp4"
    print(f"[*] Cortando primeiros 5s e patrocínio...")
    cut_and_clean_video(
        info["video_path"], clean_video,
        start_cut=5.0,
        sponsor_start=args.sponsor_start,
        sponsor_end=args.sponsor_end
    )
    
    if args.script and os.path.exists(args.script):
        script_file = Path(args.script)
    else:
        script_file = target_dir / "script_pl.txt"
        if not script_file.exists():
            print(f"[!] Aviso: script polonês não fornecido. Aguardando {script_file}")
            sys.exit(0)
            
    audio_file = target_dir / "audio_pl.mp3"
    print(f"[*] Sintetizando voz neural polonesa Marek...")
    generate_polish_audio(script_file, audio_file)
    
    final_video = target_dir / "final_pl.mp4"
    print(f"[*] Renderizando vídeo final limpo com fade-out...")
    mux_final(clean_video, audio_file, final_video)
    print(f"[+] Vídeo pronto em: {final_video}")
    
    if args.title:
        meta_file = target_dir / "upload_meta.json"
        desc = ""
        tags = "rosja, wojna, geopolityka, nato, wojna hybrydowa, wojsko, militaria, świat militarny"
        if meta_file.exists():
            with open(meta_file) as f:
                d = json.load(f)
                desc = d.get("description", "")
                tags = d.get("tags", tags)
                
        print(f"[*] Enviando para o YouTube...")
        upload_to_youtube(final_video, args.title, desc, tags, args.privacy, info["thumb_path"])
        print("[+] Processo finalizado com sucesso!")
