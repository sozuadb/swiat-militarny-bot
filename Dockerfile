FROM python:3.12-slim

# Instala dependências de sistema essenciais (FFmpeg, fontes, git, curl, unzip)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-open-sans \
    curl \
    unzip \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instala Deno (JS solver para yt-dlp no YouTube)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

# Instala dependências Python primeiro para aproveitar cache de camadas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código do repositório
COPY . .

# Comando de inicialização do bot no Railway
CMD ["python", "railway_runner.py"]
