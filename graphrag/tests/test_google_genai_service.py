import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "langchain_core.tracers.langchain_v1" not in sys.modules:
    tracer_stub = types.ModuleType("langchain_core.tracers.langchain_v1")

    class LangChainTracerV1:
        pass

    tracer_stub.LangChainTracerV1 = LangChainTracerV1
    sys.modules["langchain_core.tracers.langchain_v1"] = tracer_stub

os.environ.setdefault(
    "LOG_CONFIG",
    '{"log_file_path":"D:/github/graphrag/tests/graph_debugger/output/.tmp-test-logs","log_max_size":1048576,"log_backup_count":1}',
)

from common.llm_services import google_genai_service
from common.llm_services.google_genai_service import GoogleGenAI


def _make_config(model_name: str) -> dict:
    return {
        "llm_service": "genai",
        "llm_model": model_name,
        "authentication_configuration": {"GOOGLE_API_KEY": "test-key"},
        "model_kwargs": {"temperature": 0},
        "prompt_path": "",
    }


class TestGoogleGenAIService(unittest.TestCase):
    class _FakeCallback:
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        total_cost = 0.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeChain:
        def __init__(self, llm, sync_handler, async_handler=None):
            self.llm = llm
            self.sync_handler = sync_handler
            self.async_handler = async_handler or sync_handler

        def invoke(self, input_variables):
            return self.sync_handler(self.llm, input_variables)

        async def ainvoke(self, input_variables):
            return self.async_handler(self.llm, input_variables)

    class _FakePrompt:
        def __init__(self, sync_handler, async_handler=None):
            self.sync_handler = sync_handler
            self.async_handler = async_handler

        def __or__(self, llm):
            return TestGoogleGenAIService._FakeChain(
                llm, self.sync_handler, self.async_handler
            )

    def setUp(self):
        google_genai_service._ACTIVE_KEY_REGISTRY.clear()

    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_flash_lite_uses_shared_free_tier_limiter(self, mock_chat_model):
        service = GoogleGenAI(_make_config("gemini-3.1-flash-lite"))

        self.assertTrue(service.uses_shared_rate_limiter)
        self.assertIsNotNone(service._shared_rate_limiter)
        mock_chat_model.assert_called_once()

    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_non_flash_lite_model_does_not_enable_free_tier_limiter(
        self, mock_chat_model
    ):
        service = GoogleGenAI(_make_config("gemini-2.5-flash"))

        self.assertFalse(service.uses_shared_rate_limiter)
        self.assertIsNone(service._shared_rate_limiter)
        mock_chat_model.assert_called_once()

    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_sync_wait_for_request_slot_uses_reserved_token_budget(
        self, mock_chat_model
    ):
        service = GoogleGenAI(_make_config("gemini-3.1-flash-lite"))
        service._shared_rate_limiter.acquire = MagicMock()

        service.wait_for_request_slot({"input": "Bhishma instructed Vyasa."})

        service._shared_rate_limiter.acquire.assert_called_once()
        reserved_tokens = service._shared_rate_limiter.acquire.call_args.args[0]
        self.assertGreater(reserved_tokens, 0)

    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_async_wait_for_request_slot_uses_reserved_token_budget(
        self, mock_chat_model
    ):
        service = GoogleGenAI(_make_config("gemini-3.1-flash-lite"))
        service._shared_rate_limiter.aacquire = AsyncMock()

        asyncio.new_event_loop().run_until_complete(
            service.await_rate_limit_slot({"input": "Bhishma instructed Vyasa."})
        )

        service._shared_rate_limiter.aacquire.assert_awaited_once()
        reserved_tokens = service._shared_rate_limiter.aacquire.await_args.args[0]
        self.assertGreater(reserved_tokens, 0)

    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_context_window_guard_rejects_oversized_requests(self, mock_chat_model):
        service = GoogleGenAI(_make_config("gemini-3.1-flash-lite"))
        service._shared_rate_limiter.acquire = MagicMock()

        huge_payload = {"input": "x" * 4_100_000}

        with self.assertRaises(ValueError):
            service.wait_for_request_slot(huge_payload)

        service._shared_rate_limiter.acquire.assert_not_called()

    @patch("common.llm_services.google_genai_service.get_openai_callback")
    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_sync_invoke_rotates_to_fallback_key_on_rate_limit(
        self, mock_chat_model, mock_callback
    ):
        mock_callback.return_value = self._FakeCallback()
        mock_chat_model.side_effect = lambda **kwargs: types.SimpleNamespace(
            api_key=kwargs.get("google_api_key", "")
        )

        def sync_handler(llm, _input_variables):
            if llm.api_key == "test-key":
                raise RuntimeError("429 RESOURCE_EXHAUSTED: rate limit reached")
            return types.SimpleNamespace(content="fallback success")

        prompt = self._FakePrompt(sync_handler)
        with patch.dict(
            os.environ,
            {"GOOGLE_API_KEY_FALLBACK": "fallback-key"},
            clear=False,
        ):
            service = GoogleGenAI(_make_config("gemini-2.5-flash"))
            raw_output, usage = service._invoke_prompt_sync(
                prompt, {"question": "Who is Vyasa?"}, "sync_fallback_test"
            )

        self.assertEqual(raw_output.content, "fallback success")
        self.assertEqual(service._active_api_key, "fallback-key")
        self.assertEqual(usage["total_tokens"], 0)
        self.assertEqual(
            [call.kwargs.get("google_api_key") for call in mock_chat_model.call_args_list],
            ["test-key", "fallback-key"],
        )

    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_collects_configured_key_before_env_fallback_keys(self, mock_chat_model):
        mock_chat_model.side_effect = lambda **kwargs: types.SimpleNamespace(
            api_key=kwargs.get("google_api_key", "")
        )

        with patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY_FALLBACK": "fallback-key-a",
                "GOOGLE_API_KEY_BACKUP_1": "fallback-key-b",
                "GOOGLE_API_KEY": "test-key",
            },
            clear=False,
        ):
            service = GoogleGenAI(_make_config("gemini-2.5-flash"))

        self.assertEqual(
            service._api_keys,
            ["test-key", "fallback-key-a", "fallback-key-b"],
        )

    @patch("common.llm_services.google_genai_service.get_openai_callback")
    @patch("common.llm_services.google_genai_service.ChatGoogleGenerativeAI")
    def test_new_instances_start_with_last_successful_fallback_key(
        self, mock_chat_model, mock_callback
    ):
        mock_callback.return_value = self._FakeCallback()
        mock_chat_model.side_effect = lambda **kwargs: types.SimpleNamespace(
            api_key=kwargs.get("google_api_key", "")
        )

        def sync_handler(llm, _input_variables):
            if llm.api_key == "test-key":
                raise RuntimeError("429 RESOURCE_EXHAUSTED: rate limit reached")
            return types.SimpleNamespace(content=f"success from {llm.api_key}")

        prompt = self._FakePrompt(sync_handler)
        with patch.dict(
            os.environ,
            {"GOOGLE_API_KEY_FALLBACK": "fallback-key"},
            clear=False,
        ):
            first_service = GoogleGenAI(_make_config("gemini-2.5-flash"))
            first_output, _ = first_service._invoke_prompt_sync(
                prompt, {"question": "Who is Vyasa?"}, "first_judge"
            )

            second_service = GoogleGenAI(_make_config("gemini-2.5-flash"))
            second_output, _ = second_service._invoke_prompt_sync(
                prompt, {"question": "Who is Vyasa?"}, "second_judge"
            )

        self.assertEqual(first_output.content, "success from fallback-key")
        self.assertEqual(second_output.content, "success from fallback-key")
        self.assertEqual(second_service._active_api_key, "fallback-key")
        self.assertEqual(
            [call.kwargs.get("google_api_key") for call in mock_chat_model.call_args_list],
            ["test-key", "fallback-key", "fallback-key"],
        )


if __name__ == "__main__":
    unittest.main()
