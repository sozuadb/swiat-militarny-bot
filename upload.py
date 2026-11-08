#!/usr/bin/env python3
"""
Script de upload automatizado do YouTube Data API v3.
"""

import os
import sys
import argparse
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_authenticated_service():
    if not os.path.exists(TOKEN_FILE):
        print(f"[-] Token {TOKEN_FILE} não encontrado. Execute o auth.py primeiro!")
        sys.exit(1)

    credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        with open(TOKEN_FILE, "w") as token:
            token.write(credentials.to_json())

    return build("youtube", "v3", credentials=credentials)

def upload_video(video_path, title, description, tags=None, category_id="25", privacy_status="public", thumbnail_path=None, publish_at=None):
    if not os.path.exists(video_path):
        print(f"[-] Arquivo de vídeo não encontrado: {video_path}")
        return None

    youtube = get_authenticated_service()

    status_dict = {
        "privacyStatus": "private" if publish_at else privacy_status,
        "selfDeclaredMadeForKids": False
    }
    if publish_at:
        status_dict["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or [],
            "categoryId": category_id, # 25 = News & Politics
            "defaultLanguage": "pl",
            "defaultAudioLanguage": "pl"
        },
        "status": status_dict
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)

    print(f"[*] Enviando vídeo '{title}' para o YouTube...")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[*] Progresso do upload: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[+] Vídeo publicado com sucesso! ID: {video_id}")
    print(f"[+] URL: {video_url}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            print(f"[*] Definindo thumbnail personalizada: {thumbnail_path}")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            print("[+] Thumbnail definida com sucesso!")
        except Exception as e:
            print(f"[!] Erro ao enviar thumbnail: {e}")

    return video_url

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload de vídeo pro YouTube")
    parser.add_argument("--file", required=True, help="Caminho do arquivo de vídeo")
    parser.add_argument("--title", required=True, help="Título do vídeo")
    parser.add_argument("--desc", default="", help="Descrição do vídeo")
    parser.add_argument("--tags", default="", help="Tags separadas por vírgula")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="Privacidade")
    parser.add_argument("--thumb", default=None, help="Caminho da thumbnail")
    parser.add_argument("--publish-at", default=None, help="Data/Hora de agendamento ISO-8601 UTC (ex: 2026-11-07T15:00:00Z)")

    args = parser.parse_args()
    tags_list = [t.strip() for t in args.tags.split(",") if t.strip()]

    upload_video(
        video_path=args.file,
        title=args.title,
        description=args.desc,
        tags=tags_list,
        privacy_status=args.privacy,
        thumbnail_path=args.thumb,
        publish_at=args.publish_at
    )
