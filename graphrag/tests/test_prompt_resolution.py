import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "langchain_core.tracers.langchain_v1" not in sys.modules:
    tracer_stub = types.ModuleType("langchain_core.tracers.langchain_v1")

    class LangChainTracerV1:
        pass

    tracer_stub.LangChainTracerV1 = LangChainTracerV1
    sys.modules["langchain_core.tracers.langchain_v1"] = tracer_stub

from common.llm_services.base_llm import LLM_Model


class TestPromptResolution(unittest.TestCase):
    def test_genai_prefers_configured_entity_prompt_path_when_present(self):
        model = LLM_Model(
            {
                "prompt_path": "./common/prompts/llama_70b/",
                "llm_service": "genai",
            }
        )

        expected = (
            ROOT / "common" / "prompts" / "llama_70b" / "entity_relationship_extraction.txt"
        ).read_text(encoding="utf-8")

        self.assertEqual(model.entity_relationship_extraction_prompt, expected)

    def test_genai_falls_back_to_google_gemini_community_prompt(self):
        model = LLM_Model(
            {
                "prompt_path": "./common/prompts/llama_70b/",
                "llm_service": "genai",
            }
        )

        expected = (
            ROOT / "common" / "prompts" / "google_gemini" / "community_summarization.txt"
        ).read_text(encoding="utf-8")

        self.assertEqual(model.community_summarize_prompt, expected)

    def test_genai_falls_back_to_google_gemini_chatbot_prompt_with_strict_correction_directive(self):
        model = LLM_Model(
            {
                "prompt_path": "./common/prompts/llama_70b/",
                "llm_service": "genai",
            }
        )

        prompt = model.chatbot_response_prompt

        self.assertIn("strict knowledge graph interpreter", prompt)
        self.assertIn("false premise", prompt)
        self.assertIn("Do not merge details from separate causal chains", prompt)

    def test_genai_falls_back_to_google_gemini_retrieval_router_prompt(self):
        model = LLM_Model(
            {
                "prompt_path": "./common/prompts/llama_70b/",
                "llm_service": "genai",
            }
        )

        expected = (
            ROOT / "common" / "prompts" / "google_gemini" / "retrieval_router.txt"
        ).read_text(encoding="utf-8")

        self.assertEqual(model.retrieval_router_prompt, expected)

    @patch.object(LLM_Model, "_read_prompt_file", return_value=None)
    def test_entity_prompt_has_embedded_default_when_all_files_missing(self, _mock_read):
        model = LLM_Model({"prompt_path": "./does/not/exist/", "llm_service": "genai"})

        self.assertIn("Knowledge Graph Instructions", model.entity_relationship_extraction_prompt)

    @patch.object(LLM_Model, "_read_prompt_file", return_value=None)
    def test_community_prompt_has_embedded_default_when_all_files_missing(self, _mock_read):
        model = LLM_Model({"prompt_path": "./does/not/exist/", "llm_service": "genai"})

        self.assertIn("Description List", model.community_summarize_prompt)

    @patch.object(LLM_Model, "_read_prompt_file", return_value=None)
    def test_chatbot_prompt_has_embedded_default_when_all_files_missing(self, _mock_read):
        model = LLM_Model({"prompt_path": "./does/not/exist/", "llm_service": "genai"})

        self.assertIn("strict knowledge graph interpreter", model.chatbot_response_prompt)
        self.assertIn("false premise", model.chatbot_response_prompt)

    @patch.object(LLM_Model, "_read_prompt_file", return_value=None)
    def test_retrieval_router_prompt_has_embedded_default_when_all_files_missing(self, _mock_read):
        model = LLM_Model({"prompt_path": "./does/not/exist/", "llm_service": "genai"})

        self.assertIn("strict retrieval router", model.retrieval_router_prompt)
        self.assertIn("GRAPH", model.retrieval_router_prompt)
        self.assertIn("VECTOR", model.retrieval_router_prompt)


if __name__ == "__main__":
    unittest.main()
