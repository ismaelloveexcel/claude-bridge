#!/usr/bin/env python3
"""
Auto-patcher for idea-factory/backend/main.py

Finds the POST /api/decision endpoint and injects the bridge webhook call.
Backs up the original file before modifying.
Safe to run multiple times — detects if already patched and skips.

Usage:
    python3 patch_idea_factory.py /path/to/idea-factory
"""

import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

PATCH_MARKER = "# [claude-bridge-patch]"

IMPORT_BLOCK = '''
# [claude-bridge-patch] — auto-injected by claude-bridge setup
import hashlib
import hmac
import json as _json
import os as _os

import httpx as _httpx

_BRIDGE_URL    = _os.environ.get("BRIDGE_URL", "")
_BRIDGE_SECRET = _os.environ.get("BRIDGE_WEBHOOK_SECRET", "")
if _BRIDGE_URL and not _BRIDGE_SECRET:
    raise RuntimeError(
        "BRIDGE_WEBHOOK_SECRET env var is required when BRIDGE_URL is set. "
        "Set a strong random secret shared with claude-bridge."
    )


async def _fire_bridge_webhook(idea_data: dict):
    """Fire-and-forget webhook to claude-bridge when operator clicks Build on a GO idea."""
    if not _BRIDGE_URL:
        return
    payload = {
        "idea_id":            str(idea_data.get("id", idea_data.get("idea_id", ""))),
        "title":              idea_data.get("title", idea_data.get("idea", "Untitled")),
        "score":              int(idea_data.get("score", 0)),
        "verdict":            idea_data.get("verdict", "GO"),
        "one_liner":          idea_data.get("idea", idea_data.get("one_liner", "")),
        "problem":            idea_data.get("problem", ""),
        "solution":           idea_data.get("solution", ""),
        "target_user":        idea_data.get("target_user", ""),
        "market_research":    idea_data.get("market_research"),
        "competitor_summary": idea_data.get("competitor_summary"),
        "revenue_projection": idea_data.get("revenue_projection"),
    }
    body = _json.dumps(payload).encode()
    sig  = hmac.new(_BRIDGE_SECRET.encode(), body, hashlib.sha256).hexdigest()
    try:
        async with _httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"{_BRIDGE_URL.rstrip('/')}/webhook/idea-decision",
                content=body,
                headers={"Content-Type": "application/json", "X-Bridge-Signature": sig},
            )
    except Exception as _e:
        print(f"[claude-bridge] webhook error (non-fatal): {_e}")
# [/claude-bridge-patch]
'''

WEBHOOK_CALL = '''
        # [claude-bridge-patch] fire webhook on BUILD decision
        if _decision in ("BUILD", "build", "go", "approve") and _verdict in ("GO", "go"):
            import asyncio as _asyncio
            _asyncio.create_task(_fire_bridge_webhook(_idea_record))
        # [/claude-bridge-patch]'''


def find_main_py(repo_root: Path) -> Path:
    candidates = [
        repo_root / "backend" / "main.py",
        repo_root / "app" / "main.py",
        repo_root / "main.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Search recursively
    results = list(repo_root.rglob("main.py"))
    if results:
        return results[0]
    raise FileNotFoundError(f"Could not find main.py in {repo_root}")


def already_patched(content: str) -> bool:
    return PATCH_MARKER in content


def inject_imports(content: str) -> str:
    """Add the bridge helper functions after the last import block."""
    # Find a good insertion point: after imports, before first route
    lines = content.split("\n")
    last_import_line = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and not stripped.startswith("#"):
            last_import_line = i

    insert_after = last_import_line + 1
    lines.insert(insert_after, IMPORT_BLOCK)
    return "\n".join(lines)


def find_decision_endpoint(content: str) -> tuple[int, int]:
    """
    Find the line range of the POST /api/decision endpoint.
    Returns (start_line, end_line) 0-indexed, or (-1, -1) if not found.
    """
    lines = content.split("\n")
    start = -1
    for i, line in enumerate(lines):
        if re.search(r'@app\.(post|put)\s*\(\s*["\'].*decision', line, re.IGNORECASE):
            start = i
            break
    if start == -1:
        return -1, -1

    # Find the end of this function (next @app. decorator or end of file)
    end = len(lines) - 1
    for i in range(start + 1, len(lines)):
        if re.match(r'\s*@app\.', lines[i]) and i > start + 2:
            end = i - 1
            break

    return start, end


def inject_webhook_call(content: str) -> str:
    """
    Find the return statement in the decision endpoint and inject the webhook call before it.
    We use a heuristic: find the last `return` in the decision function block.
    """
    lines = content.split("\n")
    start, end = find_decision_endpoint(content)

    if start == -1:
        print("⚠  Could not locate POST /api/decision endpoint. Adding generic hook.")
        # Add a catch-all at the end of the file
        content += f"\n{WEBHOOK_CALL}\n"
        return content

    # Find the last return statement in the function
    last_return = -1
    for i in range(start, end + 1):
        if re.match(r'\s+return\b', lines[i]):
            last_return = i

    if last_return == -1:
        # Inject at end of function block
        last_return = end

    # Figure out indentation from the return line
    indent = re.match(r'(\s*)', lines[last_return]).group(1)

    # Build the webhook injection with matching indentation
    webhook_lines = []
    for wline in WEBHOOK_CALL.split("\n"):
        if wline.strip():
            webhook_lines.append(indent + wline.lstrip())
        else:
            webhook_lines.append("")

    lines.insert(last_return, "\n".join(webhook_lines))
    return "\n".join(lines)


def patch(repo_root_str: str):
    repo_root = Path(repo_root_str).resolve()
    if not repo_root.exists():
        print(f"❌ Repo not found: {repo_root}")
        sys.exit(1)

    main_py = find_main_py(repo_root)
    print(f"📄 Found: {main_py}")

    content = main_py.read_text(encoding="utf-8")

    if already_patched(content):
        print("✅ Already patched — nothing to do.")
        return

    # Backup
    backup = main_py.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
    shutil.copy2(main_py, backup)
    print(f"💾 Backup: {backup.name}")

    # Apply patches
    content = inject_imports(content)
    content = inject_webhook_call(content)

    main_py.write_text(content, encoding="utf-8")
    print(f"✅ Patched successfully: {main_py}")
    print("   • Bridge helper function added")
    print("   • Webhook call injected into decision endpoint")
    print("   • Original backed up")

    # Verify it's valid Python
    try:
        ast.parse(content)
        print("✅ Syntax check passed.")
    except SyntaxError as e:
        print(f"⚠  Syntax error after patch: {e}")
        print("   Restoring backup...")
        shutil.copy2(backup, main_py)
        print("   Backup restored. Please patch manually using idea_factory_patch.py as reference.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 patch_idea_factory.py /path/to/idea-factory")
        sys.exit(1)
    patch(sys.argv[1])
