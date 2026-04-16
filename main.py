"""
Claude Bridge — Integration layer between idea-factory, aidan-managing-director, and ai-dan-factory.

Designed for a non-technical solo operator. One-time setup. Fully autonomous after that.
Goal: idea validated → repo created → deployed → monetizing. Zero manual steps.

Architecture:
  idea-factory  →  [Claude Bridge]  →  aidan-managing-director  →  ai-dan-factory  →  Vercel
                        ↓
                  Claude API (BuildBrief generation + monetization design)
                        ↓
                  Telegram (operator notifications at every stage)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from anthropic import Anthropic
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from brief_generator import generate_build_brief
from notifier import notify_telegram
from state import BridgeStateDB

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("claude_bridge")

# ── Config ────────────────────────────────────────────────────────────────────
IDEA_FACTORY_URL     = os.environ["IDEA_FACTORY_URL"].rstrip("/")      # e.g. https://idea-factory.railway.app
DIRECTOR_URL         = os.environ["DIRECTOR_URL"].rstrip("/")           # e.g. https://aidan-director.railway.app
DIRECTOR_API_KEY     = os.environ.get("DIRECTOR_API_KEY", "")          # optional auth header
BRIDGE_SECRET        = os.environ.get("BRIDGE_WEBHOOK_SECRET", "changeme")
POLL_INTERVAL_SECS   = int(os.environ.get("POLL_INTERVAL_SECS", "60")) # how often to poll idea-factory
MIN_GO_SCORE         = int(os.environ.get("MIN_GO_SCORE", "70"))        # idea-factory score threshold
MIN_DIRECTOR_SCORE   = float(os.environ.get("MIN_DIRECTOR_SCORE", "8.0"))  # managing-director threshold

# ── State DB ──────────────────────────────────────────────────────────────────
db = BridgeStateDB("bridge_state.db")

# ── Lifespan (background poller) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_loop())
    log.info("✅ Claude Bridge started. Polling every %ds.", POLL_INTERVAL_SECS)
    yield
    task.cancel()

app = FastAPI(title="Claude Bridge", version="1.0.0", lifespan=lifespan)

# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK RECEIVER — idea-factory posts here on GO decision
# ══════════════════════════════════════════════════════════════════════════════

class IdeaDecisionWebhook(BaseModel):
    idea_id: str
    title: str
    score: int          # 0-100
    verdict: str        # GO / MAYBE / SKIP
    one_liner: str
    problem: str
    solution: str
    target_user: str
    market_research: Optional[str] = None
    competitor_summary: Optional[str] = None
    revenue_projection: Optional[str] = None
    tweet_thread: Optional[str] = None


@app.post("/webhook/idea-decision")
async def receive_idea_decision(
    request: Request,
    payload: IdeaDecisionWebhook,
    background_tasks: BackgroundTasks,
):
    """
    Called by idea-factory when a BUILD decision is recorded on a GO idea.
    Validates the signature, checks score, then kicks off the pipeline.
    """
    # Signature check (idea-factory must send X-Bridge-Signature header)
    body = await request.body()
    if not _verify_signature(body, request.headers.get("X-Bridge-Signature", "")):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if payload.verdict != "GO" or payload.score < MIN_GO_SCORE:
        log.info("Skipping idea %s — verdict=%s score=%d", payload.idea_id, payload.verdict, payload.score)
        return {"status": "skipped", "reason": f"verdict={payload.verdict} score={payload.score}"}

    if db.already_processed(payload.idea_id):
        log.info("Idea %s already in pipeline. Skipping duplicate.", payload.idea_id)
        return {"status": "duplicate"}

    db.mark_received(payload.idea_id, payload.dict())
    background_tasks.add_task(run_pipeline, payload)
    log.info("🚀 Pipeline triggered for idea %s: %s", payload.idea_id, payload.title)
    return {"status": "pipeline_started", "idea_id": payload.idea_id}


# ══════════════════════════════════════════════════════════════════════════════
# POLLING FALLBACK — in case idea-factory webhooks aren't configured
# ══════════════════════════════════════════════════════════════════════════════

async def poll_loop():
    """
    Polls idea-factory every POLL_INTERVAL_SECS for new GO ideas that have
    a BUILD decision recorded but haven't been sent to the director yet.
    """
    await asyncio.sleep(10)  # brief startup delay
    while True:
        try:
            await poll_idea_factory()
        except Exception as e:
            log.error("Poll error: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECS)


async def poll_idea_factory():
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{IDEA_FACTORY_URL}/api/ideas")
        resp.raise_for_status()
        ideas = resp.json()

    for idea in ideas:
        idea_id  = str(idea.get("id", ""))
        verdict  = idea.get("verdict", "")
        score    = idea.get("score", 0)
        decision = idea.get("decision", "")   # "BUILD" means operator clicked Build

        if verdict != "GO" or score < MIN_GO_SCORE:
            continue
        if decision not in ("BUILD", "build", "go"):
            continue
        if db.already_processed(idea_id):
            continue

        payload = IdeaDecisionWebhook(
            idea_id      = idea_id,
            title        = idea.get("title", idea.get("idea", "Untitled")),
            score        = score,
            verdict      = verdict,
            one_liner    = idea.get("one_liner", idea.get("idea", "")),
            problem      = idea.get("problem", ""),
            solution     = idea.get("solution", ""),
            target_user  = idea.get("target_user", ""),
            market_research     = idea.get("market_research"),
            competitor_summary  = idea.get("competitor_summary"),
            revenue_projection  = idea.get("revenue_projection"),
        )
        db.mark_received(idea_id, idea)
        asyncio.create_task(run_pipeline(payload))
        log.info("🔍 Poller found new GO idea: %s", payload.title)


# ══════════════════════════════════════════════════════════════════════════════
# CORE PIPELINE — validate → brief → director → factory → notify
# ══════════════════════════════════════════════════════════════════════════════

async def run_pipeline(idea: IdeaDecisionWebhook):
    """
    Full autonomous pipeline:
      1. Claude generates BuildBrief (with monetization baked in)
      2. Submit to aidan-managing-director
      3. Director scores and approves (or holds)
      4. If approved, factory builds + deploys
      5. Telegram notification at each stage
    """
    idea_id = idea.idea_id

    try:
        # ── Step 1: Generate BuildBrief via Claude ─────────────────────────
        log.info("[%s] Generating BuildBrief via Claude…", idea_id)
        db.update_stage(idea_id, "generating_brief")
        await notify_telegram(f"🧠 *Generating build brief* for: *{idea.title}*\nScore: {idea.score}/100")

        brief = await generate_build_brief(idea)
        db.update_stage(idea_id, "brief_ready", {"brief": brief})
        log.info("[%s] BuildBrief ready: %s", idea_id, json.dumps(brief, indent=2)[:300])

        # ── Step 2: Validate BuildBrief with Director ──────────────────────
        log.info("[%s] Validating brief with Managing Director…", idea_id)
        db.update_stage(idea_id, "validating_brief")

        async with httpx.AsyncClient(timeout=60) as client:
            headers = _director_headers()
            val_resp = await client.post(
                f"{DIRECTOR_URL}/factory/briefs/validate",
                json=brief,
                headers=headers,
            )
            val_resp.raise_for_status()
            validation = val_resp.json()

        if not validation.get("valid", False):
            log.warning("[%s] Brief validation failed: %s", idea_id, validation)
            await notify_telegram(f"⚠️ Brief validation failed for *{idea.title}*.\nReason: {validation.get('reason', 'unknown')}")
            db.update_stage(idea_id, "brief_invalid", {"validation": validation})
            return

        # ── Step 3: Submit to Director for scoring + approval ──────────────
        log.info("[%s] Submitting to Director pipeline…", idea_id)
        db.update_stage(idea_id, "submitted_to_director")

        async with httpx.AsyncClient(timeout=120) as client:
            exec_resp = await client.post(
                f"{DIRECTOR_URL}/factory/ideas/execute",
                json={"brief": brief, "auto_approve_threshold": MIN_DIRECTOR_SCORE},
                headers=headers,
            )
            exec_resp.raise_for_status()
            exec_result = exec_resp.json()

        director_score  = exec_result.get("score", 0)
        director_verdict = exec_result.get("verdict", "HOLD")
        project_id      = exec_result.get("project_id", idea_id)

        db.update_stage(idea_id, "director_scored", {
            "project_id": project_id,
            "director_score": director_score,
            "director_verdict": director_verdict,
        })

        if director_verdict == "REJECT":
            log.warning("[%s] Director rejected idea. Score: %.1f", idea_id, director_score)
            await notify_telegram(
                f"❌ *Director rejected* __{idea.title}__\n"
                f"Score: {director_score}/10\n"
                f"Reason: {exec_result.get('reason', 'Below threshold')}"
            )
            return

        if director_verdict == "HOLD":
            log.info("[%s] Director placed on HOLD. Score: %.1f", idea_id, director_score)
            await notify_telegram(
                f"⏸ *On hold:* __{idea.title}__\n"
                f"Director score: {director_score}/10 (need ≥{MIN_DIRECTOR_SCORE} to auto-approve)\n"
                f"Action needed: Review in your Managing Director dashboard and manually approve if you want to proceed."
            )
            return

        # ── Step 4: Factory building ───────────────────────────────────────
        log.info("[%s] Director APPROVED. Factory is building…", idea_id)
        db.update_stage(idea_id, "factory_building")
        await notify_telegram(
            f"🏗 *Building:* __{idea.title}__\n"
            f"Director score: {director_score}/10 ✅\n"
            f"Factory is now creating your repo and deploying…"
        )

        # Poll factory run status
        run_id   = exec_result.get("factory_run_id")
        deployed = await _wait_for_factory(idea_id, project_id, run_id)

        if not deployed:
            await notify_telegram(f"❌ *Factory build failed* for __{idea.title}__\nCheck your Managing Director dashboard.")
            db.update_stage(idea_id, "factory_failed")
            return

        # ── Step 5: Notify with live URLs ─────────────────────────────────
        deploy_url   = deployed.get("deploy_url", "")
        repo_url     = deployed.get("repo_url", "")
        checkout_url = brief.get("monetization", {}).get("checkout_url", "")

        db.update_stage(idea_id, "launched", {
            "deploy_url": deploy_url,
            "repo_url": repo_url,
            "checkout_url": checkout_url,
        })

        await notify_telegram(
            f"🚀 *LAUNCHED: {idea.title}*\n\n"
            f"🌐 Live app: {deploy_url}\n"
            f"💳 Checkout: {checkout_url or 'Set up LemonSqueezy manually'}\n"
            f"📦 Repo: {repo_url}\n\n"
            f"👉 *Next action:* Share the app link on Twitter, Indie Hackers, and Product Hunt.\n"
            f"Goal: first paying user within 7 days."
        )
        log.info("[%s] ✅ Pipeline complete. Live at %s", idea_id, deploy_url)

    except Exception as e:
        log.exception("[%s] Pipeline error: %s", idea_id, e)
        db.update_stage(idea_id, "error", {"error": str(e)})
        await notify_telegram(f"⚠️ *Pipeline error* for idea `{idea_id}`:\n`{e}`")


async def _wait_for_factory(
    idea_id: str,
    project_id: str,
    run_id: Optional[str],
    max_wait: int = 1800,  # 30 minutes
    poll_every: int = 30,
) -> Optional[dict]:
    """Polls /factory/runs/{run_id} until succeeded or failed."""
    if not run_id:
        # Fallback: poll by project
        endpoint = f"{DIRECTOR_URL}/portfolio/projects/{project_id}/events"
    else:
        endpoint = f"{DIRECTOR_URL}/factory/runs/{run_id}"

    deadline = time.time() + max_wait
    async with httpx.AsyncClient(timeout=30) as client:
        while time.time() < deadline:
            await asyncio.sleep(poll_every)
            try:
                resp = await client.get(endpoint, headers=_director_headers())
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", data.get("state", ""))
                if status in ("succeeded", "launched"):
                    return data
                if status in ("failed", "killed"):
                    return None
                log.info("[%s] Factory status: %s — waiting…", idea_id, status)
            except Exception as e:
                log.warning("[%s] Poll error: %s", idea_id, e)

    log.error("[%s] Factory timed out after %ds", idea_id, max_wait)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STATUS ENDPOINTS (operator visibility)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/status")
async def bridge_status():
    return {
        "bridge": "running",
        "processed_ideas": db.count_processed(),
        "launched": db.count_by_stage("launched"),
        "in_progress": db.count_in_progress(),
        "poll_interval_secs": POLL_INTERVAL_SECS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/pipeline/{idea_id}")
async def pipeline_status(idea_id: str):
    record = db.get(idea_id)
    if not record:
        raise HTTPException(status_code=404, detail="Idea not found in bridge")
    return record


@app.get("/health")
async def health():
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _verify_signature(body: bytes, signature: str) -> bool:
    if not signature:
        return True  # permissive if not configured
    expected = hmac.new(BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _director_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if DIRECTOR_API_KEY:
        h["Authorization"] = f"Bearer {DIRECTOR_API_KEY}"
    return h


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
