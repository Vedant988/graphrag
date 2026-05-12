# Copyright (c) 2024-2026 TigerGraph, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import hashlib
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

from common.llm_services import LLM_Model
from langchain_google_genai import ChatGoogleGenerativeAI

from common.logs.log import req_id_cv
from common.logs.logwriter import LogWriter

logger = logging.getLogger(__name__)

_FLASH_LITE_MODEL_MARKER = "gemini-3.1-flash-lite"
_FLASH_LITE_DEFAULT_LIMITS = {
    "requests_per_minute": 15,
    "requests_per_day": 1000,
    "tokens_per_minute": 250_000,
    "context_window_tokens": 1_000_000,
    "output_token_reserve": 4096,
}
_RATE_LIMITER_REGISTRY = {}
_RATE_LIMITER_REGISTRY_LOCK = threading.Lock()


class _GeminiRateLimiter:
    def __init__(
        self,
        requests_per_minute: int,
        requests_per_day: int,
        tokens_per_minute: int,
    ):
        self.requests_per_minute = max(0, int(requests_per_minute))
        self.requests_per_day = max(0, int(requests_per_day))
        self.tokens_per_minute = max(0, int(tokens_per_minute))
        self._lock = threading.Lock()
        self._request_times = deque()
        self._token_events = deque()
        self._daily_request_count = 0
        self._daily_request_day = self._current_utc_day()

    @staticmethod
    def _current_utc_day():
        return datetime.now(timezone.utc).date()

    def _prune(self, now: float) -> None:
        while self._request_times and now - self._request_times[0] >= 60.0:
            self._request_times.popleft()

        while self._token_events and now - self._token_events[0][0] >= 60.0:
            self._token_events.popleft()

        current_day = self._current_utc_day()
        if current_day != self._daily_request_day:
            self._daily_request_day = current_day
            self._daily_request_count = 0

    def _token_delay_seconds(self, now: float, reserved_tokens: int) -> float:
        if self.tokens_per_minute <= 0 or reserved_tokens <= 0:
            return 0.0
        if reserved_tokens > self.tokens_per_minute:
            raise ValueError(
                "Estimated Gemini request exceeds the configured tokens-per-minute budget."
            )

        used_tokens = sum(tokens for _, tokens in self._token_events)
        if used_tokens + reserved_tokens <= self.tokens_per_minute:
            return 0.0

        released_tokens = 0
        for timestamp, tokens in self._token_events:
            released_tokens += tokens
            if used_tokens - released_tokens + reserved_tokens <= self.tokens_per_minute:
                return max(0.0, 60.0 - (now - timestamp) + 0.05)

        oldest_timestamp = self._token_events[0][0]
        return max(0.0, 60.0 - (now - oldest_timestamp) + 0.05)

    def _acquire_delay_seconds(self, reserved_tokens: int) -> float:
        now = time.monotonic()
        self._prune(now)

        if self.requests_per_day and self._daily_request_count >= self.requests_per_day:
            raise RuntimeError(
                "Gemini free-tier daily request limit reached; refusing new requests until the next UTC day."
            )

        delays = []
        if self.requests_per_minute and len(self._request_times) >= self.requests_per_minute:
            oldest_request = self._request_times[0]
            delays.append(max(0.0, 60.0 - (now - oldest_request) + 0.05))

        token_delay = self._token_delay_seconds(now, reserved_tokens)
        if token_delay > 0:
            delays.append(token_delay)

        return max(delays, default=0.0)

    def _reserve(self, reserved_tokens: int) -> None:
        now = time.monotonic()
        self._request_times.append(now)
        self._token_events.append((now, reserved_tokens))
        self._daily_request_count += 1

    def acquire(self, reserved_tokens: int) -> None:
        while True:
            with self._lock:
                delay = self._acquire_delay_seconds(reserved_tokens)
                if delay <= 0:
                    self._reserve(reserved_tokens)
                    return
            time.sleep(delay)

    async def aacquire(self, reserved_tokens: int) -> None:
        while True:
            with self._lock:
                delay = self._acquire_delay_seconds(reserved_tokens)
                if delay <= 0:
                    self._reserve(reserved_tokens)
                    return
            await asyncio.sleep(delay)


def _stable_api_key_fingerprint(config: dict) -> str:
    auth = config.get("authentication_configuration", {}) or {}
    api_key = str(auth.get("GOOGLE_API_KEY", ""))
    if not api_key:
        return "anonymous"
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _rate_limit_overrides(config: dict) -> dict:
    model_kwargs = config.get("model_kwargs", {}) or {}
    return {
        "requests_per_minute": config.get(
            "rate_limit_requests_per_minute",
            model_kwargs.get("rate_limit_requests_per_minute"),
        ),
        "requests_per_day": config.get(
            "rate_limit_requests_per_day",
            model_kwargs.get("rate_limit_requests_per_day"),
        ),
        "tokens_per_minute": config.get(
            "rate_limit_tokens_per_minute",
            model_kwargs.get("rate_limit_tokens_per_minute"),
        ),
        "context_window_tokens": config.get(
            "rate_limit_context_window_tokens",
            model_kwargs.get("rate_limit_context_window_tokens"),
        ),
        "output_token_reserve": config.get(
            "rate_limit_output_token_reserve",
            model_kwargs.get("rate_limit_output_token_reserve"),
        ),
    }


def _resolve_rate_limits(config: dict) -> dict | None:
    model_name = str(config.get("llm_model", "")).lower()
    if _FLASH_LITE_MODEL_MARKER not in model_name:
        return None

    limits = _FLASH_LITE_DEFAULT_LIMITS.copy()
    for key, value in _rate_limit_overrides(config).items():
        if value is None:
            continue
        limits[key] = max(0, int(value))
    return limits


def _get_shared_rate_limiter(config: dict, limits: dict) -> _GeminiRateLimiter:
    registry_key = (
        str(config.get("llm_service", "")).lower(),
        str(config.get("llm_model", "")).lower(),
        _stable_api_key_fingerprint(config),
        int(limits["requests_per_minute"]),
        int(limits["requests_per_day"]),
        int(limits["tokens_per_minute"]),
    )
    with _RATE_LIMITER_REGISTRY_LOCK:
        limiter = _RATE_LIMITER_REGISTRY.get(registry_key)
        if limiter is None:
            limiter = _GeminiRateLimiter(
                requests_per_minute=limits["requests_per_minute"],
                requests_per_day=limits["requests_per_day"],
                tokens_per_minute=limits["tokens_per_minute"],
            )
            _RATE_LIMITER_REGISTRY[registry_key] = limiter
        return limiter


class GoogleGenAI(LLM_Model):
    def __init__(self, config):
        super().__init__(config)
        for auth_detail, auth_value in config.get(
            "authentication_configuration", {}
        ).items():
            os.environ[auth_detail] = auth_value

        model_name = config["llm_model"]
        self.llm = ChatGoogleGenerativeAI(
            temperature=config["model_kwargs"]["temperature"],
            model=model_name,
            timeout=None,
            max_retries=2,
        )
        self.prompt_path = config.get("prompt_path", self.prompt_path)
        self._rate_limits = _resolve_rate_limits(config)
        self._shared_rate_limiter = None
        self.uses_shared_rate_limiter = self._rate_limits is not None
        if self._rate_limits is not None:
            self._shared_rate_limiter = _get_shared_rate_limiter(
                config, self._rate_limits
            )
        LogWriter.info(
            f"request_id={req_id_cv.get()} instantiated GoogleGenAI model_name={model_name}"
        )

    def _reserved_tokens_for_payload(self, payload) -> int:
        if not self._rate_limits:
            return 0
        estimated_tokens = self.estimate_tokens(payload)
        output_reserve = max(0, int(self._rate_limits["output_token_reserve"]))
        reserved_tokens = estimated_tokens + output_reserve
        context_limit = int(self._rate_limits["context_window_tokens"])
        if context_limit and reserved_tokens > context_limit:
            raise ValueError(
                f"Estimated Gemini request requires about {reserved_tokens} tokens, "
                f"which exceeds the configured context window of {context_limit} tokens."
            )
        return reserved_tokens

    def wait_for_request_slot(self, payload=None) -> None:
        if not self._shared_rate_limiter:
            return
        self._shared_rate_limiter.acquire(self._reserved_tokens_for_payload(payload))

    async def await_rate_limit_slot(self, payload=None) -> None:
        if not self._shared_rate_limiter:
            return
        await self._shared_rate_limiter.aacquire(
            self._reserved_tokens_for_payload(payload)
        )
