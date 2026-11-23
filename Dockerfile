FROM python:3.12-slim

# Instala dependências de sistema essenciais (FFmpeg, fontes para thumbnail, git e curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-open-sans \
    curl \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala dependências Python primeiro para aproveitar cache de camadas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código do repositório
COPY . .

# Comando de inicialização do bot no Railway
CMD ["python", "railway_runner.py"]
