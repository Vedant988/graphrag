import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "LOG_CONFIG",
    '{"log_file_path":"D:/github/graphrag/.tmp_test_logs","log_max_size":1048576,"log_backup_count":0}',
)

if "langchain_core.tracers.langchain_v1" not in sys.modules:
    tracer_stub = types.ModuleType("langchain_core.tracers.langchain_v1")

    class LangChainTracerV1:
        pass

    tracer_stub.LangChainTracerV1 = LangChainTracerV1
    sys.modules["langchain_core.tracers.langchain_v1"] = tracer_stub

ROUTER_PATH = ROOT / "graphrag" / "app" / "agent" / "retrieval_router.py"
ROUTER_SPEC = importlib.util.spec_from_file_location(
    "retrieval_router_under_test",
    ROUTER_PATH,
)
retrieval_router_under_test = importlib.util.module_from_spec(ROUTER_SPEC)
assert ROUTER_SPEC and ROUTER_SPEC.loader
sys.modules["retrieval_router_under_test"] = retrieval_router_under_test
ROUTER_SPEC.loader.exec_module(retrieval_router_under_test)

RetrievalRouteResponse = retrieval_router_under_test.RetrievalRouteResponse
TigerGraphSupportAIRouter = retrieval_router_under_test.TigerGraphSupportAIRouter


class TestTigerGraphSupportAIRouter(unittest.TestCase):
    def test_multi_hop_question_routes_to_graph_without_llm_call(self):
        llm = MagicMock()
        llm.retrieval_router_prompt = "Question: {question}\nFormat: {format_instructions}"
        router = TigerGraphSupportAIRouter(llm)

        decision = router.route_question(
            "Based entirely on the first 10 pages, trace the exact lineage and mentorship connections between the author of the Mahabharata and the warrior who was left lying on a bed of arrows. How are they connected?"
        )

        self.assertEqual(decision.route, "GRAPH")
        self.assertEqual(decision.source, "heuristic")
        self.assertIn("request", decision.reason)
        llm.invoke_with_parser.assert_not_called()

    def test_simple_lookup_routes_to_vector_without_llm_call(self):
        llm = MagicMock()
        llm.retrieval_router_prompt = "Question: {question}\nFormat: {format_instructions}"
        router = TigerGraphSupportAIRouter(llm)

        decision = router.route_question(
            "What role does Ganesa play in the composition of the Mahabharata?"
        )

        self.assertEqual(decision.route, "VECTOR")
        self.assertEqual(decision.source, "heuristic")
        self.assertEqual(decision.reason, "simple_lookup_pattern")
        llm.invoke_with_parser.assert_not_called()

    def test_ambiguous_question_uses_llm_classifier(self):
        llm = MagicMock()
        llm.retrieval_router_prompt = "Question: {question}\nFormat: {format_instructions}"
        llm.invoke_with_parser.return_value = RetrievalRouteResponse(route="graph")
        router = TigerGraphSupportAIRouter(llm)

        decision = router.route_question(
            "After the king heard the news, what followed next?"
        )

        self.assertEqual(decision.route, "GRAPH")
        self.assertEqual(decision.source, "llm")
        self.assertEqual(decision.reason, "llm_classifier")
        llm.invoke_with_parser.assert_called_once()

    def test_relation_graph_profile_uses_two_hops_and_three_candidates(self):
        llm = MagicMock()
        llm.retrieval_router_prompt = "Question: {question}\nFormat: {format_instructions}"
        router = TigerGraphSupportAIRouter(llm)

        profile = router.graph_profile_for_question(
            "Based entirely on the first 10 pages, trace the exact lineage and mentorship connections between the author of the Mahabharata and the warrior who was left lying on a bed of arrows. How are they connected?"
        )

        self.assertEqual(profile.name, "relation_graph")
        self.assertEqual(profile.num_hops, 2)
        self.assertEqual(profile.top_k, 5)
        self.assertFalse(profile.chunk_only)
        self.assertEqual(profile.max_score_candidates, 5)

    def test_aggregation_graph_profile_uses_seen_count_filter(self):
        llm = MagicMock()
        llm.retrieval_router_prompt = "Question: {question}\nFormat: {format_instructions}"
        router = TigerGraphSupportAIRouter(llm)

        profile = router.graph_profile_for_question(
            "Across the entire 10 pages, what are the primary justifications or root causes given for the destruction of the Kshatriya race or the massive loss of life in the war? Aggregate the distinct reasons."
        )

        self.assertEqual(profile.name, "aggregation_graph")
        self.assertEqual(profile.num_hops, 2)
        self.assertEqual(profile.num_seen_min, 2)
        self.assertEqual(profile.max_score_candidates, 4)

    def test_factoid_graph_profile_stays_lightweight(self):
        llm = MagicMock()
        llm.retrieval_router_prompt = "Question: {question}\nFormat: {format_instructions}"
        router = TigerGraphSupportAIRouter(llm)

        profile = router.graph_profile_for_question("Who is the father of Arjuna?")

        self.assertEqual(profile.name, "factoid_graph")
        self.assertEqual(profile.num_hops, 1)
        self.assertEqual(profile.top_k, 2)
        self.assertEqual(profile.max_score_candidates, 2)


if __name__ == "__main__":
    unittest.main()
