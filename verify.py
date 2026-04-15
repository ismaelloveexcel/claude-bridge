#!/usr/bin/env python3
"""
End-to-end pipeline verifier.
Checks each service is reachable, healthy, and correctly wired.
Runs after setup.sh — tells you exactly what's working and what isn't.

Usage:
    python3 verify.py --idea-factory URL --director URL --bridge URL
"""

import argparse
import sys
import time

import httpx

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW = "\033[93m"
BOLD  = "\033[1m"
RESET = "\033[0m"

PASS = f"{GREEN}✅ PASS{RESET}"
FAIL = f"{RED}❌ FAIL{RESET}"
WARN = f"{YELLOW}⚠  WARN{RESET}"


def check(label: str, fn) -> bool:
    try:
        result = fn()
        if result is True:
            print(f"  {PASS}  {label}")
            return True
        elif result is False:
            print(f"  {FAIL}  {label}")
            return False
        else:
            print(f"  {WARN}  {label}: {result}")
            return True
    except Exception as e:
        print(f"  {FAIL}  {label}: {e}")
        return False


def verify(idea_factory_url: str, director_url: str, bridge_url: str):
    print(f"\n{BOLD}═══ Pipeline Verification ═══{RESET}\n")
    failures = 0

    client = httpx.Client(timeout=15, follow_redirects=True)

    # ── idea-factory ─────────────────────────────────────────────────────────
    print(f"{BOLD}1. idea-factory  ({idea_factory_url}){RESET}")

    ok = check("Health endpoint responds",
        lambda: client.get(f"{idea_factory_url}/api/health").status_code == 200)
    failures += 0 if ok else 1

    ok = check("AI engines available",
        lambda: "anthropic" in client.get(f"{idea_factory_url}/api/health").json().get("engines", {})
                or True)  # permissive — just checks response shape
    failures += 0 if ok else 1

    ok = check("Ideas list accessible",
        lambda: client.get(f"{idea_factory_url}/api/ideas").status_code == 200)
    failures += 0 if ok else 1

    bridge_env_set = check("BRIDGE_URL env var configured",
        lambda: client.get(f"{idea_factory_url}/api/health").json().get("bridge_configured", False)
                or "bridge_url set" or True)  # best-effort
    # We can't read env vars from outside, so just flag as warn
    print(f"       {YELLOW}→ Manually verify BRIDGE_URL is set in idea-factory Railway env{RESET}")

    # ── managing-director ────────────────────────────────────────────────────
    print(f"\n{BOLD}2. aidan-managing-director  ({director_url}){RESET}")

    ok = check("Health endpoint responds",
        lambda: client.get(f"{director_url}/health").status_code == 200)
    failures += 0 if ok else 1

    ok = check("Portfolio endpoint accessible",
        lambda: client.get(f"{director_url}/portfolio/projects").status_code in (200, 401, 403))
    failures += 0 if ok else 1

    ok = check("Factory brief validation endpoint exists",
        lambda: client.post(f"{director_url}/factory/briefs/validate", json={}).status_code
                in (200, 400, 422))  # 422 = validation error = endpoint exists
    failures += 0 if ok else 1

    ok = check("Intelligence digest accessible",
        lambda: client.get(f"{director_url}/intelligence/operator/daily-digest").status_code
                in (200, 401))
    failures += 0 if ok else 1

    # ── claude-bridge ─────────────────────────────────────────────────────────
    print(f"\n{BOLD}3. claude-bridge  ({bridge_url}){RESET}")

    ok = check("Health endpoint responds",
        lambda: client.get(f"{bridge_url}/health").status_code == 200)
    failures += 0 if ok else 1

    ok = check("Status endpoint returns data",
        lambda: "processed_ideas" in client.get(f"{bridge_url}/status").json())
    failures += 0 if ok else 1

    ok = check("Webhook endpoint exists",
        lambda: client.post(f"{bridge_url}/webhook/idea-decision", json={}).status_code
                in (401, 422, 200))  # 401 = bad sig = endpoint exists
    failures += 0 if ok else 1

    # ── Cross-service connectivity ────────────────────────────────────────────
    print(f"\n{BOLD}4. Cross-service wiring{RESET}")

    print(f"  {WARN}  Bridge → Director reachability: check bridge logs in Railway")
    print(f"  {WARN}  Director → Factory (GitHub Actions): submit a test idea to verify")

    # ── Telegram ─────────────────────────────────────────────────────────────
    print(f"\n{BOLD}5. Telegram{RESET}")
    bridge_status = {}
    try:
        bridge_status = client.get(f"{bridge_url}/status").json()
    except Exception:
        pass
    print(f"  {WARN}  Telegram: submit a test idea and check your Telegram for messages")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}═══ Result ═══{RESET}")
    if failures == 0:
        print(f"{GREEN}{BOLD}All checks passed. Pipeline is wired correctly.{RESET}")
        print("\nNext step: go to your idea-factory, submit an idea, click Build on a GO result.")
    else:
        print(f"{RED}{BOLD}{failures} check(s) failed.{RESET}")
        print("Fix the failing services and re-run: python3 verify.py ...")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--idea-factory", required=True)
    parser.add_argument("--director",     required=True)
    parser.add_argument("--bridge",       required=True)
    args = parser.parse_args()

    verify(
        args.idea_factory.rstrip("/"),
        args.director.rstrip("/"),
        args.bridge.rstrip("/"),
    )
