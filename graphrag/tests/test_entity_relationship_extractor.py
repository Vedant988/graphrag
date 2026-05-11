import sys
import asyncio
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

    def test_json_to_graph_document_accepts_structured_like_payload(self):
        payload = {
            "nodes": [
                {
                    "id": "Vyasa",
                    "type": "Person",
                    "node_type": "Person",
                    "definition": "Author of the epic.",
                    "properties": "{}",
                },
                {
                    "id": "Ganesa",
                    "type": "Deity",
                    "node_type": "Deity",
                    "definition": "Divine scribe.",
                    "properties": "{\"description\": \"Divine scribe.\"}",
                },
            ],
            "rels": [
                {
                    "source": {
                        "id": "Vyasa",
                        "type": "Person",
                        "node_type": "Person",
                        "definition": "Author of the epic.",
                        "properties": "{}",
                    },
                    "target": {
                        "id": "Ganesa",
                        "type": "Deity",
                        "node_type": "Deity",
                        "definition": "Divine scribe.",
                        "properties": "{}",
                    },
                    "type": "DICTATES_TO",
                    "relation_type": "DICTATES_TO",
                    "definition": "Vyasa dictates and Ganesa writes.",
                    "properties": "{}",
                }
            ],
        }

        graph_documents = self.extractor._json_to_graph_document(payload, "sample")

        self.assertEqual(len(graph_documents), 1)
        self.assertEqual(graph_documents[0].nodes[0].id, "Vyasa")
        self.assertEqual(graph_documents[0].relationships[0].type, "DICTATES_TO")

    def test_aextract_returns_graph_documents_for_async_callers(self):
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
            "adocument_er_graph_documents",
            return_value=[graph_doc],
        ) as mock_graph_docs:
            result = asyncio.new_event_loop().run_until_complete(
                self.extractor.aextract("Mahabharata sample")
            )

        mock_graph_docs.assert_called_once_with("Mahabharata sample")
        self.assertEqual(result, [graph_doc])


if __name__ == "__main__":
    unittest.main()
