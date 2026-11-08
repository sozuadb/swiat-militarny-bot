# Świat Militarny — 24/7 Autonomous Cloud Pipeline

Pipeline autônomo de dublagem, edição e publicação em polonês para o canal **Świat Militarny** (`@SwiatMilitarny`).

## ⚙️ Arquitetura Serverless (GitHub Actions)
- **Disparo:** Cron agendado a cada 30 minutos (`*/30 * * * *`) + `workflow_dispatch` manual.
- **Monitoramento:** Coleta os vídeos mais recentes de `@hojenomundomilitar`.
- **Corte Inteligente:** Remove vinheta de 3 segundos e detecta trechos de patrocinadores para concatenação limpa.
- **Voz Neural:** Síntese em polonês com a voz neural `pl-PL-MarekNeural` via Edge-TTS.
- **Renderização:** FFmpeg unindo vídeo tratado com áudio polonês (0% áudio original, fade-out de 3s).
- **Publicação:** YouTube Data API v3 com status público e thumbnail original.
- **Persistência de Estado:** O arquivo `processed_ids.json` é atualizado e comitado automaticamente pelo bot do GitHub Actions.

## 🔒 Secrets Configurados
- `CLIENT_SECRETS_JSON`: Credenciais da aplicação Google Cloud Console.
- `TOKEN_JSON`: Token OAuth2 com refresh token para autenticação no YouTube.
