import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.extractors import LLMEntityRelationshipExtractor
from common.py_schemas import Document as RepoDocument
from langchain_community.graphs.graph_document import GraphDocument, Node, Relationship
from langchain_core.documents import Document


class TestLLMEntityRelationshipExtractor(unittest.TestCase):
    def setUp(self):
        self.llm_service = MagicMock()
        self.extractor = LLMEntityRelationshipExtractor(self.llm_service)

    def test_graph_documents_to_dict_preserves_nodes_and_relationships(self):
        source = Node(
            id="Vyasa",
            type="Person",
            properties={"description": "Author of the epic."},
        )
        target = Node(
            id="Ganesa",
            type="Deity",
            properties={"description": "Divine scribe."},
        )
        graph_doc = GraphDocument(
            nodes=[source, target],
            relationships=[
                Relationship(
                    source=source,
                    target=target,
                    type="DICTATES_TO",
                    properties={"description": "Vyasa dictates and Ganesa writes."},
                )
            ],
            source=Document(page_content="sample"),
        )

        normalized = self.extractor._graph_documents_to_dict([graph_doc])

        self.assertEqual(
            normalized["nodes"],
            [
                {
                    "id": "Vyasa",
                    "type": "Person",
                    "definition": "Author of the epic.",
                },
                {
                    "id": "Ganesa",
                    "type": "Deity",
                    "definition": "Divine scribe.",
                },
            ],
        )
        self.assertEqual(
            normalized["rels"],
            [
                {
                    "source": "Vyasa",
                    "target": "Ganesa",
                    "type": "DICTATES_TO",
                    "definition": "Vyasa dictates and Ganesa writes.",
                }
            ],
        )

    def test_document_er_extraction_accepts_repo_document_objects(self):
        repo_doc = RepoDocument(document_id="doc-1", text="Mahabharata sample")
        graph_doc = GraphDocument(
            nodes=[
                Node(
                    id="Sauti",
                    type="Narrator",
                    properties={"description": "Narrates the story."},
                )
            ],
            relationships=[],
            source=Document(page_content="Mahabharata sample"),
        )

        with patch.object(
            self.extractor,
            "document_er_graph_documents",
            return_value=[graph_doc],
        ) as mock_graph_docs:
            normalized = self.extractor.document_er_extraction(repo_doc)

        mock_graph_docs.assert_called_once_with(repo_doc)
        self.assertEqual(
            normalized,
            {
                "nodes": [
                    {
                        "id": "Sauti",
                        "type": "Narrator",
                        "definition": "Narrates the story.",
                    }
                ],
                "rels": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
