import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCORING_UTILS_PATH = (
    ROOT / "graphrag" / "app" / "supportai" / "retrievers" / "scoring_utils.py"
)
SCORING_UTILS_SPEC = importlib.util.spec_from_file_location(
    "scoring_utils_under_test",
    SCORING_UTILS_PATH,
)
scoring_utils_under_test = importlib.util.module_from_spec(SCORING_UTILS_SPEC)
assert SCORING_UTILS_SPEC and SCORING_UTILS_SPEC.loader
sys.modules["scoring_utils_under_test"] = scoring_utils_under_test
SCORING_UTILS_SPEC.loader.exec_module(scoring_utils_under_test)

limit_contexts_for_scoring = scoring_utils_under_test.limit_contexts_for_scoring


class TestRetrieverScoring(unittest.TestCase):
    def test_limit_contexts_prefers_question_overlap(self):
        question = "How are Vyasa and Bhishma connected?"
        contexts = [
            "Vyasa and Bhishma are connected through an explicit enjoined relationship.",
            "Bhishma was later found lying on a bed of arrows.",
            "The harvest season was prosperous and peaceful.",
        ]

        limited = limit_contexts_for_scoring(
            question,
            contexts,
            max_candidates=2,
        )

        self.assertEqual(limited, contexts[:2])


if __name__ == "__main__":
    unittest.main()
