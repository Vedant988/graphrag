import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestEccProcessId(unittest.TestCase):
    def _mocked_modules(self) -> dict[str, MagicMock]:
        graphrag_pkg = MagicMock()
        graphrag_pkg.reusable_channel = MagicMock()
        graphrag_pkg.workers = MagicMock()

        supportai_pkg = MagicMock()
        supportai_pkg.workers = MagicMock()

        extractor_pkg = MagicMock()
        extractor_pkg.GraphExtractor = MagicMock()
        extractor_pkg.LLMEntityRelationshipExtractor = MagicMock()

        return {
            "graphrag": graphrag_pkg,
            "supportai": supportai_pkg,
            "common.config": MagicMock(
                graphrag_config={},
                embedding_service=MagicMock(),
                get_llm_service=MagicMock(),
                get_completion_config=MagicMock(),
                get_graphrag_config=MagicMock(return_value={}),
            ),
            "common.embeddings.base_embedding_store": MagicMock(EmbeddingStore=MagicMock()),
            "common.embeddings.tigergraph_embedding_store": MagicMock(
                TigerGraphEmbeddingStore=MagicMock()
            ),
            "common.extractors": extractor_pkg,
            "common.extractors.BaseExtractor": MagicMock(BaseExtractor=MagicMock()),
            "common.logs.logwriter": MagicMock(LogWriter=MagicMock()),
        }

    def test_graphrag_process_id_accepts_integer_ids(self):
        with patch.dict(sys.modules, self._mocked_modules()):
            module = _load_module(
                "ecc_graphrag_util_under_test",
                "ecc/app/graphrag/util.py",
            )

        self.assertEqual(module.process_id(12345), "12345")

    def test_supportai_process_id_accepts_integer_ids(self):
        with patch.dict(sys.modules, self._mocked_modules()):
            module = _load_module(
                "ecc_supportai_util_under_test",
                "ecc/app/supportai/util.py",
            )

        self.assertEqual(module.process_id(67890), "67890")


if __name__ == "__main__":
    unittest.main()
