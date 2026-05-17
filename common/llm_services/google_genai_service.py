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
from langchain_community.callbacks.manager import get_openai_callback
from langchain_google_genai import ChatGoogleGenerativeAI

from common.logs.log import req_id_cv
from common.logs.logwriter import LogWriter
from common.utils.gemini_fallback import collect_gemini_api_keys, is_gemini_rate_limit_error

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
_ACTIVE_KEY_REGISTRY = {}
_ACTIVE_KEY_REGISTRY_LOCK = threading.Lock()


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


def _stable_api_key_fingerprint(config: dict, api_key: str | None = None) -> str:
    if api_key is None:
        auth = config.get("authentication_configuration", {}) or {}
        api_key = str(auth.get("GOOGLE_API_KEY", ""))
    if not api_key:
        return "anonymous"
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _active_key_registry_key(config: dict, api_keys: list[str]) -> tuple:
    return (
        str(config.get("llm_service", "")).lower(),
        str(config.get("llm_model", "")).lower(),
        tuple(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] for key in api_keys),
    )


def _initial_active_key_index(config: dict, api_keys: list[str]) -> int:
    if not api_keys:
        return 0
    registry_key = _active_key_registry_key(config, api_keys)
    with _ACTIVE_KEY_REGISTRY_LOCK:
        last_healthy_key = _ACTIVE_KEY_REGISTRY.get(registry_key)
    if last_healthy_key in api_keys:
        return api_keys.index(last_healthy_key)
    return 0


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


def _get_shared_rate_limiter(
    config: dict, limits: dict, api_key: str | None = None
) -> _GeminiRateLimiter:
    registry_key = (
        str(config.get("llm_service", "")).lower(),
        str(config.get("llm_model", "")).lower(),
        _stable_api_key_fingerprint(config, api_key),
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
        self._client_lock = threading.Lock()
        self._model_name = model_name
        self._temperature = config["model_kwargs"]["temperature"]
        self._api_keys = collect_gemini_api_keys(config)
        self._active_key_registry_key = _active_key_registry_key(config, self._api_keys)
        self._llm_clients: dict[str, ChatGoogleGenerativeAI] = {}
        self._active_api_key_index = _initial_active_key_index(config, self._api_keys)
        self._active_api_key = self._api_keys[0] if self._api_keys else ""
        if self._api_keys:
            self._active_api_key = self._api_keys[self._active_api_key_index]
        self.prompt_path = config.get("prompt_path", self.prompt_path)
        self._rate_limits = _resolve_rate_limits(config)
        self._rate_limiters_by_key: dict[str, _GeminiRateLimiter] = {}
        self._shared_rate_limiter = None
        self.uses_shared_rate_limiter = self._rate_limits is not None
        self.llm = self._client_for_key(self._active_api_key)
        self._shared_rate_limiter = self._rate_limiter_for_key(self._active_api_key)
        LogWriter.info(
            f"request_id={req_id_cv.get()} instantiated GoogleGenAI model_name={model_name} "
            f"with {max(1, len(self._api_keys))} configured Gemini key(s)"
        )

    def _build_client(self, api_key: str | None):
        kwargs = {
            "temperature": self._temperature,
            "model": self._model_name,
            "timeout": None,
            "max_retries": 2,
        }
        if api_key:
            kwargs["google_api_key"] = api_key
            os.environ["GOOGLE_API_KEY"] = api_key
        return ChatGoogleGenerativeAI(**kwargs)

    def _client_for_key(self, api_key: str | None):
        cache_key = api_key or "__default__"
        client = self._llm_clients.get(cache_key)
        if client is None:
            client = self._build_client(api_key)
            self._llm_clients[cache_key] = client
        return client

    def _rate_limiter_for_key(self, api_key: str | None):
        if self._rate_limits is None:
            return None
        cache_key = api_key or "__default__"
        limiter = self._rate_limiters_by_key.get(cache_key)
        if limiter is None:
            limiter = _get_shared_rate_limiter(self.config, self._rate_limits, api_key)
            self._rate_limiters_by_key[cache_key] = limiter
        return limiter

    def _set_active_key_unlocked(self, index: int) -> None:
        self._active_api_key_index = index
        self._active_api_key = self._api_keys[index] if self._api_keys else ""
        self.llm = self._client_for_key(self._active_api_key)
        self._shared_rate_limiter = self._rate_limiter_for_key(self._active_api_key)
        if self._active_api_key:
            with _ACTIVE_KEY_REGISTRY_LOCK:
                _ACTIVE_KEY_REGISTRY[self._active_key_registry_key] = self._active_api_key

    def _active_client_state(self):
        with self._client_lock:
            return (
                self._active_api_key_index,
                self._active_api_key,
                self.llm,
                self._shared_rate_limiter,
            )

    def _activate_next_key(self, attempted_keys: set[str]) -> bool:
        if len(self._api_keys) <= 1:
            return False
        with self._client_lock:
            for offset in range(1, len(self._api_keys)):
                next_index = (self._active_api_key_index + offset) % len(self._api_keys)
                next_key = self._api_keys[next_index]
                if next_key in attempted_keys:
                    continue
                self._set_active_key_unlocked(next_index)
                return True
        return False

    def _invoke_prompt_sync(self, prompt, input_variables: dict, caller_name: str = "unknown"):
        attempted_keys: set[str] = set()
        last_exc = None

        while True:
            _, api_key, llm, limiter = self._active_client_state()
            attempted_keys.add(api_key or "__default__")
            try:
                chain = prompt | llm
                usage_data = {}
                with get_openai_callback() as cb:
                    if limiter is not None:
                        limiter.acquire(self._reserved_tokens_for_payload(input_variables))
                    raw_output = chain.invoke(input_variables)
                    usage_data["input_tokens"] = cb.prompt_tokens
                    usage_data["output_tokens"] = cb.completion_tokens
                    usage_data["total_tokens"] = cb.total_tokens
                    usage_data["cost"] = cb.total_cost
                return raw_output, usage_data
            except Exception as exc:
                last_exc = exc
                if not is_gemini_rate_limit_error(exc):
                    raise
                if not self._activate_next_key(attempted_keys):
                    raise
                LogWriter.warning(
                    f"{caller_name} hit Gemini rate limits on the active key; "
                    "rotating to the next configured fallback key."
                )

        raise last_exc  # pragma: no cover

    async def _invoke_prompt_async(self, prompt, input_variables: dict, caller_name: str = "unknown"):
        attempted_keys: set[str] = set()
        last_exc = None

        while True:
            _, api_key, llm, limiter = self._active_client_state()
            attempted_keys.add(api_key or "__default__")
            try:
                chain = prompt | llm
                usage_data = {}
                with get_openai_callback() as cb:
                    if limiter is not None:
                        await limiter.aacquire(
                            self._reserved_tokens_for_payload(input_variables)
                        )
                    raw_output = await chain.ainvoke(input_variables)
                    usage_data["input_tokens"] = cb.prompt_tokens
                    usage_data["output_tokens"] = cb.completion_tokens
                    usage_data["total_tokens"] = cb.total_tokens
                    usage_data["cost"] = cb.total_cost
                return raw_output, usage_data
            except Exception as exc:
                last_exc = exc
                if not is_gemini_rate_limit_error(exc):
                    raise
                if not self._activate_next_key(attempted_keys):
                    raise
                LogWriter.warning(
                    f"{caller_name} hit Gemini rate limits on the active key; "
                    "rotating to the next configured fallback key."
                )

        raise last_exc  # pragma: no cover

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
