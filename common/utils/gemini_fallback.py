import os
import re

try:
    from google.api_core.exceptions import ResourceExhausted, TooManyRequests
except Exception:  # pragma: no cover - defensive import fallback
    ResourceExhausted = ()  # type: ignore[assignment]
    TooManyRequests = ()  # type: ignore[assignment]


_EXACT_ENV_VARS = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY_FALLBACK",
    "GEMINI_API_KEY_FALLBACK",
)
_LIST_ENV_VARS = (
    "GOOGLE_API_KEYS",
    "GEMINI_API_KEYS",
    "GOOGLE_API_KEY_FALLBACKS",
    "GEMINI_API_KEY_FALLBACKS",
)
_FALLBACK_ENV_KEY_RE = re.compile(r"^(GOOGLE|GEMINI)_API_KEY(?:_[A-Z0-9]+)+$")
_RATE_LIMIT_PATTERNS = (
    "429",
    "resource_exhausted",
    "resource exhausted",
    "quota",
    "rate limit",
    "daily request limit",
    "too many requests",
)
_GEMINI_INPUT_COST_PER_TOKEN = 0.25 / 1_000_000
_GEMINI_OUTPUT_COST_PER_TOKEN = 1.50 / 1_000_000


def _split_key_list(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [part.strip() for part in re.split(r"[,;\r\n]+", raw_value) if part.strip()]


def collect_gemini_api_keys(config: dict | None) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        keys.append(normalized)

    auth = (config or {}).get("authentication_configuration", {}) or {}
    add(auth.get("GOOGLE_API_KEY"))
    add(auth.get("GEMINI_API_KEY"))
    add(auth.get("GOOGLE_API_KEY_FALLBACK"))
    add(auth.get("GEMINI_API_KEY_FALLBACK"))

    for auth_name, auth_value in auth.items():
        if auth_name in {
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY_FALLBACK",
            "GEMINI_API_KEY_FALLBACK",
        }:
            continue
        if _FALLBACK_ENV_KEY_RE.match(str(auth_name)):
            add(str(auth_value))

    for env_name in _EXACT_ENV_VARS:
        add(os.getenv(env_name))

    for env_name in _LIST_ENV_VARS:
        for item in _split_key_list(os.getenv(env_name)):
            add(item)

    for env_name in sorted(os.environ):
        if env_name in _EXACT_ENV_VARS or env_name in _LIST_ENV_VARS:
            continue
        if _FALLBACK_ENV_KEY_RE.match(env_name):
            add(os.getenv(env_name))

    return keys


def is_gemini_rate_limit_error(exc: Exception) -> bool:
    if ResourceExhausted and isinstance(exc, ResourceExhausted):
        return True
    if TooManyRequests and isinstance(exc, TooManyRequests):
        return True

    message = str(exc).lower()
    return any(pattern in message for pattern in _RATE_LIMIT_PATTERNS)


def calculate_gemini_token_cost(
    input_tokens: int | float | None,
    output_tokens: int | float | None,
    *,
    precision: int = 6,
) -> float:
    normalized_input = max(0, int(input_tokens or 0))
    normalized_output = max(0, int(output_tokens or 0))
    total_cost = (
        normalized_input * _GEMINI_INPUT_COST_PER_TOKEN
        + normalized_output * _GEMINI_OUTPUT_COST_PER_TOKEN
    )
    return round(total_cost, precision)
