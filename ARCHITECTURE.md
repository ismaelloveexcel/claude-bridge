# AIDAN System — Full Architecture & Service Map

## What is AIDAN?

AIDAN (AI-Driven Autonomous Network) is a fully automated product monetisation pipeline. You submit a business idea — the system validates, evaluates, builds, deploys, and notifies you. Zero manual steps after submission.

## System Flow

```
You (browser)
     │
     ▼
┌─────────────────────────────────┐
│  1. IDEA FACTORY                │  ← Submit your idea here
│  idea-factory-production-3ada   │
│  .up.railway.app                │
└─────────────┬───────────────────┘
              │ Scores idea (GO / NO-GO)
              │ If GO → posts webhook to AIDAN Bridge
              ▼
┌─────────────────────────────────┐
│  2. AIDAN BRIDGE                │  ← Orchestration hub
│  aidan-bridge-production        │    Polls idea-factory every 60s
│  .up.railway.app                │    Routes GO ideas to Managing Director
└─────────────┬───────────────────┘
              │ Sends idea brief to Managing Director
              ▼
┌─────────────────────────────────┐
│  3. AIDAN MANAGING DIRECTOR     │  ← Evaluation & dispatch
│  aidan-managing-director-       │    Scores the brief (0–10)
│  production.up.railway.app      │    If ≥ 8.0 → triggers Factory build
└─────────────┬───────────────────┘
              │ Triggers GitHub Actions job
              ▼
┌─────────────────────────────────┐
│  4. AI-DAN FACTORY              │  ← Builder / deployer
│  ai-dan-factory-production      │    Builds the product from the brief
│  .up.railway.app                │    Deploys it live
└─────────────┬───────────────────┘
              │
              ▼
        📱 Telegram (@AIDAN2026_bot)
        Sends you the live product URL
```

## Services at a Glance

| Service | Repo | Live URL | Role |
|---------|------|----------|------|
| Idea Factory | `ismaelloveexcel/idea-factory` | `idea-factory-production-3ada.up.railway.app` | Validate & score ideas |
| AIDAN Bridge | `ismaelloveexcel/claude-bridge` | `aidan-bridge-production.up.railway.app` | Orchestration hub |
| AIDAN Managing Director | `ismaelloveexcel/aidan-managing-director` | `aidan-managing-director-production.up.railway.app` | Evaluate briefs & dispatch builds |
| AI-DAN Factory | `ismaelloveexcel/ai-dan-factory` | `ai-dan-factory-production.up.railway.app` | Build & deploy products |

All services hosted on **Railway** under workspace `281564ad-34d2-4079-ae47-a1b6526ff817`.

## Scoring Thresholds

| Gate | Setting | Meaning |
|------|---------|---------|
| `MIN_GO_SCORE` | 70 | Idea Factory score ≥ 70 → forwarded to Bridge |
| `MIN_DIRECTOR_SCORE` | 8.0 | Managing Director score ≥ 8.0 → Factory builds it |

## Webhook Security

All inter-service webhooks are HMAC-SHA256 signed using `BRIDGE_WEBHOOK_SECRET` / `FACTORY_CALLBACK_SECRET`. Both must contain the **same value** across all services. Current canonical secret is stored as `BRIDGE_WEBHOOK_SECRET` on the AIDAN Bridge service in Railway.

## Telegram Notifications

The system sends build status updates to **@AIDAN2026_bot** on Telegram.
- Bot token: stored as `TELEGRAM_BOT_TOKEN` on Bridge + Managing Director
- Chat ID: stored as `TELEGRAM_CHAT_ID` on Bridge + Managing Director

## Key Env Vars Per Service

### Idea Factory
| Var | Purpose |
|-----|---------|
| `BRIDGE_URL` | Where to POST GO decisions (`https://aidan-bridge-production.up.railway.app`) |
| `BRIDGE_WEBHOOK_SECRET` | Signs outgoing webhooks |
| `ANTHROPIC_API_KEY` | AI scoring |
| `OPENAI_API_KEY` | AI scoring fallback |
| `ADMIN_SECRET` | Admin endpoint protection |

### AIDAN Bridge
| Var | Purpose |
|-----|---------|
| `IDEA_FACTORY_URL` | Polls this for GO ideas |
| `DIRECTOR_URL` | Sends briefs here |
| `BRIDGE_WEBHOOK_SECRET` | Verifies incoming webhooks |
| `TELEGRAM_BOT_TOKEN` | Sends Telegram alerts |
| `TELEGRAM_CHAT_ID` | Your Telegram chat (`6447150424`) |
| `POLL_INTERVAL_SECS` | How often to poll (60s) |
| `MIN_GO_SCORE` | Minimum idea score to forward (70) |
| `MIN_DIRECTOR_SCORE` | Minimum director score to build (8.0) |

### AIDAN Managing Director
| Var | Purpose |
|-----|---------|
| `FACTORY_CALLBACK_SECRET` | Signs callbacks to Factory |
| `FACTORY_OWNER` | GitHub org/user (`ismaelloveexcel`) |
| `FACTORY_REPO` | Factory repo name (`ai-dan-factory`) |
| `GITHUB_TOKEN` | Triggers GitHub Actions in Factory |
| `ANTHROPIC_API_KEY` | AI evaluation |
| `TELEGRAM_BOT_TOKEN` | Sends Telegram alerts |
| `TELEGRAM_CHAT_ID` | Your Telegram chat |

### AI-DAN Factory
| Var | Purpose |
|-----|---------|
| `FACTORY_GITHUB_TOKEN` | Access for deployment |
| `FACTORY_OWNER` | GitHub owner |

## How to Use the System

1. Open **https://idea-factory-production-3ada.up.railway.app**
2. Type your business idea
3. Fill in operator constraints (hours, budget, audience, skills)
4. Click **Validate**
5. If the idea scores GO (≥ 70), click **BUILD**
6. Wait for a Telegram message on @AIDAN2026_bot with your live product URL

## Monitoring

- Bridge status: `https://aidan-bridge-production.up.railway.app/status`
- Bridge health: `https://aidan-bridge-production.up.railway.app/health`
- Pipeline for specific idea: `https://aidan-bridge-production.up.railway.app/pipeline/{idea_id}`
- MD health: `https://aidan-managing-director-production.up.railway.app/health`

## Railway Project IDs (for admin)

| Service | Project ID | Service ID | Env ID |
|---------|-----------|-----------|--------|
| Idea Factory | `36b37c68-...` | `9cc55cf9-...` | `2adc9677-...` |
| AIDAN Bridge | `5e558d71-...` | `03c0d6ee-...` | `8b0b9d99-...` |
| Managing Director | `c3f12a08-...` | `24e768d9-...` | `439131e2-...` |
| AI-DAN Factory | `5b01d0dc-...` | `a5e12cd6-...` | `c739d01c-...` |

## Deployment History

Deployed April 2026 via Railway GraphQL API + GitHub Contents API. All services use Nixpacks builder with explicit `startCommand` set via `serviceInstanceUpdate` to avoid Railway config conflicts.
