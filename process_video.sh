#!/usr/bin/env bash
# Wrapper para processamento de vídeos do canal Świat Militarny
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$DIR/venv/bin:$PATH"

if [ -z "$1" ]; then
    echo "Uso: ./process_video.sh <URL_YOUTUBE> [OPÇÕES]"
    echo "Exemplo: ./process_video.sh 'https://www.youtube.com/watch?v=...' --sponsor-start 27 --sponsor-end 57"
    exit 1
fi

python3 "$DIR/pipeline.py" "$@"
