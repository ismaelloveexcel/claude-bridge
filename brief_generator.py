"""
BuildBrief Generator — uses Claude to convert idea-factory validation output
into a structured BuildBrief that aidan-managing-director and ai-dan-factory expect.

Monetization is mandatory. Every brief must have:
  - Pricing model
  - Price point
  - LemonSqueezy checkout structure
  - First 10 users plan
  - Single distribution channel
"""

import json
import os
import re
import uuid
from typing import Any

from anthropic import AsyncAnthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Which model to use for brief generation
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-6")


async def generate_build_brief(idea: Any) -> dict:
    """
    Takes idea-factory validation output → returns a valid BuildBrief dict.
    Uses Claude to fill gaps, invent monetization, and structure the output.
    """
    prompt = _build_prompt(idea)

    response = await claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text
    brief = _extract_json(raw)

    # Ensure idea_id and project_id are set
    brief["project_id"] = f"{_slugify(idea.title)}-{idea.idea_id[:6]}"
    brief["idea_id"]    = idea.idea_id
    brief["source"]     = "idea-factory"
    brief["validation_score"] = idea.score

    return brief


def _build_prompt(idea: Any) -> str:
    return f"""You are a venture product designer. Your job is to convert a validated business idea into a precise BuildBrief JSON that an automated factory will use to build, deploy, and monetize a product.

VALIDATED IDEA:
Title: {idea.title}
One-liner: {idea.one_liner}
Problem: {idea.problem or 'Not specified — infer from title and one-liner'}
Solution: {idea.solution or 'Not specified — infer from problem'}
Target user: {idea.target_user or 'Not specified — define the most specific viable user'}
Validation score: {idea.score}/100
Market research: {idea.market_research or 'Not available'}
Competitor summary: {idea.competitor_summary or 'Not available'}
Revenue projection: {idea.revenue_projection or 'Not available'}

CONSTRAINTS:
- Non-technical solo founder. The factory must build something that works with minimal custom code.
- Monetization is MANDATORY. Every field in the monetization block must be filled.
- Charge from day one. No "free and figure it out later."
- Single distribution channel only — the one with the highest probability of reaching the first 10 paying users.
- Target region: USA first unless the idea is specifically regional.
- The product must be buildable as a Next.js 14 app in 7 days or fewer.
- MVP = 3 features maximum. Everything else is backlog.

OUTPUT: Return a single valid JSON object with EXACTLY this schema. No explanation, no markdown, just JSON.

{{
  "product_name": "url-safe-slug-max-30-chars",
  "title": "Human readable product name",
  "problem": "One sentence — the pain the user feels right now",
  "solution": "One sentence — what the product does",
  "cta": "The call-to-action button text on the landing page (5 words max)",
  "target_user": "Hyper-specific person description (job title, situation, pain)",
  "source_type": "saas",
  "reference_context": "Brief context about why this idea scored GO",
  "demand_level": "high|medium|low",
  "monetization_proof": "Evidence that people pay for this type of solution",
  "market_saturation": "low|medium|high",
  "differentiation": "What makes this different from existing solutions in one sentence",
  "build_complexity": "low",
  "speed_to_revenue": "high",
  "mvp_features": [
    "Feature 1 — core value delivery",
    "Feature 2 — essential support feature",
    "Feature 3 — monetization gate"
  ],
  "monetization": {{
    "model": "freemium|subscription|one-time|usage-based",
    "price_usd": 29,
    "price_description": "e.g. $29/month per user",
    "free_tier_limit": "What free users get (keep it tight to push upgrades)",
    "paid_tier_value": "What paid users get that free users don't",
    "checkout_url": "",
    "competitive_edge": "Why users pay this vs alternatives"
  }},
  "distribution": {{
    "primary_channel": "The single best channel to reach the first 10 paying users",
    "first_10_users_plan": "Exact tactical steps to find and convert the first 10 paying users",
    "region": "USA",
    "launch_copy_hook": "One sentence that makes someone click — lead with their pain"
  }},
  "landing_page": {{
    "headline": "Outcome-focused headline (not feature-focused)",
    "subheadline": "Who this is for and what they get",
    "social_proof_placeholder": "What type of testimonial/proof to collect first"
  }},
  "scores": {{
    "overall": {min(int(idea.score / 10), 10)},
    "feasibility": 8,
    "profitability": 8,
    "speed": 9,
    "competition": 7
  }},
  "verdict": "APPROVE"
}}

Be specific and opinionated. Do not use generic placeholders. Fill every field with real, actionable content based on the idea provided."""


def _extract_json(text: str) -> dict:
    """Extract JSON from Claude's response, handling markdown code blocks."""
    # Try to find JSON block
    patterns = [
        r"```json\s*([\s\S]+?)\s*```",
        r"```\s*([\s\S]+?)\s*```",
        r"(\{[\s\S]+\})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    # Last resort: try to parse the whole thing
    return json.loads(text)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:30]
