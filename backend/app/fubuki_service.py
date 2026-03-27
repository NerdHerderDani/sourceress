from __future__ import annotations

import os
from typing import Any

import httpx


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

# Prefer env override so prod/dev can pin whatever Anthropic model is available.
# NOTE: Model availability depends on the Anthropic account. We'll retry a small fallback list
# on "model not found" errors to reduce setup pain.
MODEL = (os.environ.get('ANTHROPIC_MODEL') or '').strip() or "claude-sonnet-4-6"

FALLBACK_MODELS = [
    # Your account's model ids (from /v1/models). Order: faster/cheaper -> stronger.
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-6",
    "claude-opus-4-20250514",
    "claude-opus-4-1-20250805",
    "claude-opus-4-5-20251101",
    "claude-opus-4-6",
]


def _api_key(override: str | None = None) -> str:
    # Prefer explicit override (per-request), then env var.
    if override and override.strip():
        return override.strip()
    return (os.environ.get('ANTHROPIC_API_KEY') or '').strip()


def anthropic_list_models(api_key: str | None = None) -> list[dict[str, Any]]:
    """Return models visible to the current Anthropic API key."""
    key = _api_key(api_key)
    if not key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY env var")

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }

    with httpx.Client(timeout=30.0) as client:
        r = client.get(ANTHROPIC_MODELS_URL, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic API error {r.status_code}: {r.text}")
        data = r.json() if r.content else {}

    # Expected: { data: [ {id, display_name, ...}, ...] }
    items = data.get('data')
    return items if isinstance(items, list) else []


def fubuki_call_ex(
    system: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    max_tokens: int = 1200,
    api_key: str | None = None,
    system_blocks: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call Anthropic and return (text, meta).

    You can pass either:
      - system (string)
      - OR system_blocks (Anthropic "system" content array) for per-layer caching.

    meta includes:
      - model_used
      - usage (raw usage dict if present)
      - input_tokens/output_tokens (best-effort)
    """
    if messages is None:
        messages = []

    key = _api_key(api_key)
    if not key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY (env var) and no per-request key provided")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }

    models_to_try = [MODEL] + [m for m in FALLBACK_MODELS if m and m != MODEL]
    last_err: str | None = None

    # Normalize system payload
    if system_blocks is not None:
        sys_payload = system_blocks
    else:
        sys_payload = [
            {
                "type": "text",
                "text": (system or ''),
                # Anthropic prompt caching: cache the (usually static) system prompt.
                "cache_control": {"type": "ephemeral"},
            }
        ]

    with httpx.Client(timeout=30.0) as client:
        for mdl in models_to_try:
            payload = {
                "model": mdl,
                "max_tokens": int(max_tokens),
                "system": sys_payload,
                "messages": messages,
            }

            r = client.post(ANTHROPIC_URL, headers=headers, json=payload)
            if r.status_code >= 400:
                # Retry only on "model not found".
                txt = r.text or ''
                last_err = f"Anthropic API error {r.status_code}: {txt}"
                if r.status_code == 404 and 'model:' in txt:
                    continue
                raise RuntimeError(last_err)

            data = r.json() if r.content else {}
            usage = data.get('usage') if isinstance(data, dict) else None

            meta: dict[str, Any] = {
                'model_used': data.get('model') or mdl,
                'usage': usage if isinstance(usage, dict) else {},
            }
            if isinstance(usage, dict):
                # Anthropic commonly uses input_tokens/output_tokens
                if isinstance(usage.get('input_tokens'), int):
                    meta['input_tokens'] = usage.get('input_tokens')
                if isinstance(usage.get('output_tokens'), int):
                    meta['output_tokens'] = usage.get('output_tokens')

            # Anthropic returns content: [{type:'text', text:'...'}]
            parts = data.get('content') or []
            for p in parts:
                if isinstance(p, dict) and p.get('type') == 'text':
                    return (p.get('text') or '').strip(), meta

            # If we can't find a text block, fail loudly so the UI doesn't show a fake "No response".
            ptypes = []
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict) and p.get('type'):
                        ptypes.append(str(p.get('type')))
            raise RuntimeError(
                f"Anthropic response had no text content blocks. content_types={ptypes} raw_keys={list(data.keys())}"
            )

    raise RuntimeError(last_err or 'Anthropic API error: unknown')


def fubuki_call(system: str, messages: list[dict[str, Any]], max_tokens: int = 1200, api_key: str | None = None) -> str:
    text, _meta = fubuki_call_ex(system=system, messages=messages, max_tokens=max_tokens, api_key=api_key)
    return text
