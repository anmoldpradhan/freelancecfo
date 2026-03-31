"""
Transaction categorisation service using Google Gemini 2.0 Flash-Lite.

Design decisions:
- Batches transactions (max 30 per API call) to stay within token limits
- Deterministic rules checked FIRST — no API call needed for known merchants
- Falls back to "Uncategorised" on any failure — never crashes the import
- Input sanitised to prevent prompt injection
- Full observability via structured logging
"""

import json
import logging
import time
import re
import asyncio
from typing import Optional
import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

from app.core.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── Gemini client ─────────────────────────────────────────────────────────────
genai.configure(api_key=settings.gemini_api_key)
model = genai.GenerativeModel("gemini-2.5-flash-lite")

# ── Constants ─────────────────────────────────────────────────────────────────
BATCH_SIZE = 25          # transactions per API call
MAX_RETRIES = 3          # retry attempts on API/parse failure
RETRY_BASE_DELAY = 2.0   # seconds — doubles each retry (exponential backoff)
API_TIMEOUT = 30.0       # seconds before we give up on a Gemini call
CONFIDENCE_THRESHOLD = 0.75  # below this → is_confirmed = False

# ── Deterministic rules (checked before any API call) ────────────────────────
# Format: lowercase substring → (category_name, confidence)
DETERMINISTIC_RULES: dict[str, tuple[str, float]] = {
    "amazon web services": ("Software & Subscriptions", 0.99),
    "aws.amazon":          ("Software & Subscriptions", 0.99),
    "github":              ("Software & Subscriptions", 0.99),
    "google workspace":    ("Software & Subscriptions", 0.99),
    "figma":               ("Software & Subscriptions", 0.99),
    "notion":              ("Software & Subscriptions", 0.99),
    "slack":               ("Software & Subscriptions", 0.99),
    "digitalocean":        ("Software & Subscriptions", 0.99),
    "stripe":              ("Client Income",            0.95),
    "paypal":              ("Client Income",            0.90),
    "uber eats":           ("Travel",                   0.95),
    "uber":                ("Travel",                   0.92),
    "trainline":           ("Travel",                   0.97),
    "hmrc":                ("Professional Fees",        0.99),
    "inland revenue":      ("Professional Fees",        0.99),
    "accountant":          ("Professional Fees",        0.95),
    "solicitor":           ("Professional Fees",        0.95),
    "freelance invoice":   ("Freelance Payment",        0.97),
    "client payment":      ("Client Income",            0.96),
    "invoice #":           ("Client Income",            0.93),
}

# ── Few-shot examples embedded in prompt ──────────────────────────────────────
FEW_SHOT_EXAMPLES = """\
Examples (use EXACT category names from the list above):
1. "AMAZON WEB SERVICES" | amount: -49.99  → Software & Subscriptions, 0.97
2. "Client payment ACME Ltd" | amount: 2500.00 → Client Income, 0.96
3. "UBER EATS" | amount: -23.50 → Travel, 0.88
4. "HMRC Self Assessment" | amount: -350.00 → Professional Fees, 0.99
5. "Office supplies Staples" | amount: -34.99 → Office & Equipment, 0.91
6. "Unknown merchant XYZ" | amount: -12.00 → Uncategorised, 0.40\
"""


# ── Input sanitisation ────────────────────────────────────────────────────────

def _sanitise(text: str, max_length: int = 120) -> str:
    """
    Removes characters that could break JSON or inject prompt instructions.
    Truncates to max_length to prevent token bloat.
    """
    # Strip control characters and common injection patterns
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)          # control chars
    cleaned = re.sub(r"(ignore|forget|disregard).{0,30}(above|previous|instruction)",
                     "[removed]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```", "", cleaned)                       # code fences
    cleaned = cleaned.replace('"', "'")                         # prevent JSON breakage
    return cleaned.strip()[:max_length]


# ── Deterministic pre-check ───────────────────────────────────────────────────

def _check_deterministic(
    description: str,
    category_map: dict[str, str],
) -> Optional[tuple[str, float]]:
    """
    Returns (category_name, confidence) if description matches a known rule.
    Returns None if no rule matches — caller must use Gemini.
    Only returns a match if the category actually exists in this tenant's schema.
    """
    desc_lower = description.lower()
    for keyword, (cat_name, confidence) in DETERMINISTIC_RULES.items():
        if keyword in desc_lower and cat_name in category_map:
            return cat_name, confidence
    return None


# ── Response validation ───────────────────────────────────────────────────────

def _validate_and_extract(
    raw_response: str,
    expected_count: int,
    valid_category_names: set[str],
    fallback_category: str,
) -> list[dict]:
    """
    Parses and validates Gemini's JSON response.
    Returns a safe list of {index, category_name, confidence} dicts.
    Any malformed / hallucinated entry gets fallback_category + confidence 0.0.
    """
    # Strip markdown fences
    text = raw_response.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Gemini JSON parse failed: %s | raw: %.200s", e, raw_response)
        # Return all-fallback list
        return [
            {"index": i + 1, "category_name": fallback_category, "confidence": 0.0}
            for i in range(expected_count)
        ]

    if not isinstance(parsed, list):
        logger.warning("Gemini response is not a list: %s", type(parsed))
        return [
            {"index": i + 1, "category_name": fallback_category, "confidence": 0.0}
            for i in range(expected_count)
        ]

    validated = []
    seen_indices = set()

    for item in parsed:
        if not isinstance(item, dict):
            continue

        # Validate index
        try:
            idx = int(item["index"])
        except (KeyError, TypeError, ValueError):
            continue

        if idx < 1 or idx > expected_count or idx in seen_indices:
            continue
        seen_indices.add(idx)

        # Validate category — normalise whitespace/case, reject hallucinations
        raw_cat = str(item.get("category_name", "")).strip()
        # Case-insensitive match against valid names
        matched_cat = next(
            (v for v in valid_category_names
             if v.lower() == raw_cat.lower()),
            None
        )
        if not matched_cat:
            logger.debug("Hallucinated category '%s' → fallback", raw_cat)
            matched_cat = fallback_category

        # Validate + clamp confidence
        try:
            confidence = float(item.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))  # clamp to [0, 1]
        except (TypeError, ValueError):
            confidence = 0.0

        validated.append({
            "index": idx,
            "category_name": matched_cat,
            "confidence": confidence,
        })

    # Fill any missing indices with fallback
    present = {v["index"] for v in validated}
    for i in range(1, expected_count + 1):
        if i not in present:
            validated.append({
                "index": i,
                "category_name": fallback_category,
                "confidence": 0.0,
            })

    return sorted(validated, key=lambda x: x["index"])


# ── Single batch API call with retry ─────────────────────────────────────────

async def _categorise_batch(
    batch: list[dict],
    available_categories: list[dict],
    fallback_category: str,
) -> list[dict]:
    """
    Sends one batch to Gemini. Retries up to MAX_RETRIES on failure.
    Always returns a result — never raises.
    """
    categories_text = "\n".join(
        f"- {c['name']} ({c['type']})" for c in available_categories
    )
    valid_names = {c["name"] for c in available_categories}

    transactions_text = "\n".join(
        f"{i + 1}. \"{_sanitise(t['description'])}\" | amount: {t['amount']}"
        for i, t in enumerate(batch)
    )

    prompt = f"""You are a UK freelancer financial categorisation assistant.

AVAILABLE CATEGORIES (use EXACT names, case-sensitive):
{categories_text}

{FEW_SHOT_EXAMPLES}

RULES:
- Positive amounts = income, negative = expenses
- Use ONLY category names from the list above — no variations
- If unsure, use "Uncategorised"
- Respond with ONLY a JSON array — no explanation, no markdown, no extra text
- JSON must be valid and parseable by Python's json.loads()

TRANSACTIONS TO CATEGORISE:
{transactions_text}

REQUIRED JSON FORMAT:
[
  {{"index": 1, "category_name": "EXACT name from list", "confidence": 0.95}},
  {{"index": 2, "category_name": "EXACT name from list", "confidence": 0.80}}
]"""

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            start = time.monotonic()

            response = await asyncio.wait_for(
                asyncio.to_thread(model.generate_content, prompt),
                timeout=API_TIMEOUT,
            )

            latency = time.monotonic() - start
            raw = response.text

            logger.debug(
                "Gemini response | attempt=%d latency=%.2fs batch_size=%d raw=%.300s",
                attempt + 1, latency, len(batch), raw
            )

            results = _validate_and_extract(
                raw, len(batch), valid_names, fallback_category
            )

            # Log confidence distribution
            confidences = [r["confidence"] for r in results]
            low_conf = sum(1 for c in confidences if c < CONFIDENCE_THRESHOLD)
            logger.info(
                "Batch categorised | size=%d low_confidence=%d avg_conf=%.2f latency=%.2fs",
                len(batch), low_conf,
                sum(confidences) / len(confidences) if confidences else 0,
                latency,
            )

            return results

        except asyncio.TimeoutError:
            last_error = "Gemini API timeout"
            logger.warning("Gemini timeout on attempt %d/%d", attempt + 1, MAX_RETRIES)

        except GoogleAPIError as e:
            last_error = str(e)
            logger.warning("Gemini API error attempt %d/%d: %s", attempt + 1, MAX_RETRIES, e)

        except Exception as e:
            last_error = str(e)
            logger.error("Unexpected error attempt %d/%d: %s", attempt + 1, MAX_RETRIES, e)

        if attempt < MAX_RETRIES - 1:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.info("Retrying in %.1fs...", delay)
            await asyncio.sleep(delay)

    # All retries exhausted
    logger.error(
        "All %d Gemini attempts failed for batch of %d. Last error: %s. Using fallback.",
        MAX_RETRIES, len(batch), last_error
    )
    return [
        {"index": i + 1, "category_name": fallback_category, "confidence": 0.0}
        for i in range(len(batch))
    ]


# ── Public interface ──────────────────────────────────────────────────────────

async def categorise_transactions(
    transactions: list[dict],
    available_categories: list[dict],
) -> list[dict]:
    """
    Categorises a list of transactions using deterministic rules + Gemini.

    Args:
        transactions: [{"description": "...", "amount": 123.45, ...}, ...]
        available_categories: [{"id": "...", "name": "...", "type": "..."}, ...]

    Returns:
        Same list with category_id, category_name, confidence added in-place.
        Never raises — falls back to Uncategorised on any failure.

    Mutates input dicts directly (documents here so callers know).
    """
    if not transactions:
        return []

    if not available_categories:
        logger.error("No categories available — all transactions will be Uncategorised")
        for t in transactions:
            t["category_id"] = None
            t["category_name"] = "Uncategorised"
            t["confidence"] = 0.0
        return transactions

    category_map = {c["name"]: c["id"] for c in available_categories}
    fallback_category = "Uncategorised"

    # Guarantee fallback exists — if tenant has no Uncategorised, use first category
    if fallback_category not in category_map:
        fallback_category = available_categories[0]["name"]
        logger.warning("No 'Uncategorised' category found — using '%s'", fallback_category)

    # ── Phase 1: deterministic rules (no API call) ────────────────────────────
    needs_gemini: list[int] = []          # indices of transactions that need API

    for i, t in enumerate(transactions):
        match = _check_deterministic(t.get("description", ""), category_map)
        if match:
            cat_name, confidence = match
            t["category_id"] = category_map[cat_name]
            t["category_name"] = cat_name
            t["confidence"] = confidence
            logger.debug("Deterministic match: '%s' → %s", t["description"], cat_name)
        else:
            needs_gemini.append(i)

    logger.info(
        "Categorisation | total=%d deterministic=%d needs_gemini=%d",
        len(transactions),
        len(transactions) - len(needs_gemini),
        len(needs_gemini),
    )

    if not needs_gemini:
        return transactions

    # ── Phase 2: Gemini in batches ────────────────────────────────────────────
    for batch_start in range(0, len(needs_gemini), BATCH_SIZE):
        batch_indices = needs_gemini[batch_start: batch_start + BATCH_SIZE]
        batch = [transactions[i] for i in batch_indices]

        results = await _categorise_batch(batch, available_categories, fallback_category)

        # Map results back to original transaction list
        for result in results:
            original_idx = batch_indices[result["index"] - 1]
            cat_name = result["category_name"]
            transactions[original_idx]["category_id"] = category_map.get(cat_name)
            transactions[original_idx]["category_name"] = cat_name
            transactions[original_idx]["confidence"] = result["confidence"]

    return transactions