import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
            "_adocument_er_graph_documents",
            AsyncMock(return_value=[graph_doc]),
        ) as mock_graph_docs:
            result = asyncio.new_event_loop().run_until_complete(
                self.extractor.aextract("Mahabharata sample")
            )

        mock_graph_docs.assert_called_once_with("Mahabharata sample")
        self.assertEqual(result, [graph_doc])

    def test_aextract_retries_suspiciously_empty_chunks_with_fallback_prompt(self):
        lineage_text = (
            "Krishna-Dwaipayana, by the injunctions of Bhishma and his own mother, "
            "became the father of three boys by the two wives of Vichitra-virya. "
            "Having thus raised up Dhritarashtra, Pandu, and Vidura, he returned "
            "to his recluse abode to prosecute his religious exercise."
        )
        empty_graph = GraphDocument(
            nodes=[],
            relationships=[],
            source=Document(page_content=lineage_text),
        )
        retry_graph = GraphDocument(
            nodes=[
                Node(
                    id="Vyasa",
                    type="Person",
                    properties={"description": "Father of Dhritarashtra."},
                ),
                Node(
                    id="Dhritarashtra",
                    type="Person",
                    properties={"description": "One of the three sons."},
                ),
            ],
            relationships=[
                Relationship(
                    source=Node(id="Vyasa", type="Person"),
                    target=Node(id="Dhritarashtra", type="Person"),
                    type="father_of",
                    properties={"description": "Vyasa fathers Dhritarashtra."},
                )
            ],
            source=Document(page_content=lineage_text),
        )

        with patch.object(
            self.extractor,
            "_arun_graph_documents",
            AsyncMock(side_effect=[[empty_graph], [retry_graph]]),
        ) as mock_extract:
            result = asyncio.new_event_loop().run_until_complete(
                self.extractor.aextract(lineage_text)
            )

        self.assertEqual(result, [retry_graph])
        self.assertEqual(mock_extract.await_count, 2)
        self.assertIsNone(mock_extract.await_args_list[0].kwargs.get("extra_instruction"))
        retry_instruction = (
            mock_extract.await_args_list[1].kwargs.get("extra_instruction")
            or mock_extract.await_args_list[1].args[1]
        )
        self.assertIn(
            "genealogical",
            retry_instruction.lower(),
        )

    def test_aextract_does_not_retry_short_truly_empty_chunks(self):
        bland_text = "No names or family relations here."
        empty_graph = GraphDocument(
            nodes=[],
            relationships=[],
            source=Document(page_content=bland_text),
        )

        with patch.object(
            self.extractor,
            "_arun_graph_documents",
            AsyncMock(return_value=[empty_graph]),
        ) as mock_extract:
            result = asyncio.new_event_loop().run_until_complete(
                self.extractor.aextract(bland_text)
            )

        self.assertEqual(result, [empty_graph])
        self.assertEqual(mock_extract.await_count, 1)

    def test_async_request_slot_delegates_to_llm_service_limiter(self):
        self.extractor.llm_service.uses_shared_rate_limiter = True
        self.extractor.llm_service.await_rate_limit_slot = AsyncMock()

        payload = {"input": "Mahabharata sample"}
        asyncio.new_event_loop().run_until_complete(
            self.extractor._await_async_request_slot(payload)
        )

        self.extractor.llm_service.await_rate_limit_slot.assert_awaited_once_with(
            payload
        )

    def test_sync_request_slot_delegates_to_llm_service_limiter(self):
        self.extractor.llm_service.uses_shared_rate_limiter = True
        self.extractor.llm_service.wait_for_request_slot = MagicMock()

        payload = {"input": "Mahabharata sample"}
        self.extractor._wait_for_request_slot(payload)

        self.extractor.llm_service.wait_for_request_slot.assert_called_once_with(
            payload
        )


if __name__ == "__main__":
    unittest.main()
