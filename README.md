# AIDAN Bridge

The orchestration hub of the AIDAN autonomous product pipeline. It sits between **Idea Factory** and **AIDAN Managing Director**, polling for validated ideas and routing them through the build pipeline.

## What it does

1. **Polls** Idea Factory every 60 seconds for ideas that scored GO (≥ 70)
2. **Validates** incoming webhooks from Idea Factory (HMAC-SHA256)
3. **Routes** GO ideas to AIDAN Managing Director for deeper evaluation
4. **Tracks** pipeline state for every idea (pending → evaluating → building → launched)
5. **Notifies** via Telegram at key pipeline milestones

## System Position

```
Idea Factory → [AIDAN BRIDGE] → Managing Director → AI-DAN Factory → Telegram
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full system diagram.

## Live URL

```
https://aidan-bridge-production.up.railway.app
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check → `{"status":"ok"}` |
| `/status` | GET | Pipeline stats (processed, launched, in-progress) |
| `/pipeline/{idea_id}` | GET | Status of a specific idea |
| `/webhook/idea-decision` | POST | Receives GO decisions from Idea Factory |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `IDEA_FACTORY_URL` | URL of Idea Factory to poll |
| `DIRECTOR_URL` | URL of AIDAN Managing Director |
| `BRIDGE_WEBHOOK_SECRET` | HMAC secret — must match Idea Factory's `BRIDGE_WEBHOOK_SECRET` |
| `ANTHROPIC_API_KEY` | For any AI-assisted routing logic |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID for notifications |
| `POLL_INTERVAL_SECS` | How often to poll Idea Factory (default: 60) |
| `MIN_GO_SCORE` | Minimum score to forward (default: 70) |
| `MIN_DIRECTOR_SCORE` | Minimum MD score to trigger build (default: 8.0) |
| `PORT` | HTTP port (default: 8080) |

## Running Locally

```bash
pip install fastapi uvicorn httpx
export IDEA_FACTORY_URL=https://idea-factory-production-3ada.up.railway.app
export DIRECTOR_URL=https://aidan-managing-director-production.up.railway.app
export BRIDGE_WEBHOOK_SECRET=<your-secret>
export TELEGRAM_BOT_TOKEN=<your-token>
export TELEGRAM_CHAT_ID=<your-chat-id>
python main.py
```

## Deployment

Hosted on Railway. Service ID: `03c0d6ee-bfbe-4a67-b708-77c4a5ff231e`  
Builder: Nixpacks | Start command: `sh -c 'uvicorm main:app --host 0.0.0.0 --port ${PORT:-8080}'`

> **Note:** The Railway service is named `aidan-bridge` in project `claude-bridge`.  
> The GitHub repo remains `ismaelloveexcel/claude-bridge` for historical reasons.

## Connected Services

| Service | Relationship |
|---------|-------------|
| `ismaelloveexcel/idea-factory` | Polls this for GO ideas; receives webhooks from it |
| `ismaelloveexcel/aidan-managing-director` | Forwards ideas to this for evaluation |
| `ismaelloveexcel/ai-dan-factory` | Triggered indirectly via Managing Director |
