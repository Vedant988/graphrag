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
import logging
import json
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List

from common.extractors.BaseExtractor import BaseExtractor
from common.py_schemas import KnowledgeGraph
from langchain_community.graphs.graph_document import Node, Relationship, GraphDocument
from langchain_core.documents import Document

if TYPE_CHECKING:
    from common.llm_services.base_llm import LLM_Model
else:
    LLM_Model = Any

logger = logging.getLogger(__name__)


class LLMEntityRelationshipExtractor(BaseExtractor):
    EMPTY_EXTRACTION_FALLBACK_INSTRUCTION = """The previous extraction attempt returned a valid schema but zero entities and relationships.
Retry with a narrower mandate:
- Extract named people, groups, places, works, and other relationally important actors.
- Prioritize genealogical, kinship, lineage, marriage, alias, request, instruction, and causal relationships.
- Preserve important unnamed but referential actors as entities when needed, such as "his own mother" or "the two wives of Vichitra-virya".
- Prefer returning a partial but useful graph over an empty graph when the passage contains substantive actors or relations.
- If the passage truly contains no extractable entities or relations, return empty lists."""

    def __init__(
        self,
        llm_service: LLM_Model,
        allowed_entity_types: List[str] = None,
        allowed_relationship_types: List[str] = None,
        strict_mode: bool = False,
        empty_extraction_retries: int = 1,
        suspicious_empty_min_chars: int = 160,
    ):
        self.llm_service = llm_service
        self.allowed_vertex_types = allowed_entity_types
        self.allowed_edge_types = allowed_relationship_types
        self.strict_mode = strict_mode
        self.empty_extraction_retries = max(0, empty_extraction_retries)
        self.suspicious_empty_min_chars = max(0, suspicious_empty_min_chars)
        self._async_request_lock = asyncio.Lock()
        self._last_async_request_started_at = 0.0
        self._min_request_interval_seconds = self._resolve_min_request_interval_seconds()

    def _coerce_text(self, document: Any) -> str:
        """Accept either plain text or repo document objects."""
        if isinstance(document, str):
            return document

        text = getattr(document, "text", None)
        if text is not None:
            return text

        page_content = getattr(document, "page_content", None)
        if page_content is not None:
            return page_content

        return str(document)

    def _empty_graph_document(self, doc_text: str) -> List[GraphDocument]:
        return [
            GraphDocument(
                nodes=[],
                relationships=[],
                source=Document(page_content=doc_text),
            )
        ]

    def _parse_json_output(self, content: str) -> dict:
        """Parse JSON from LLM output with multiple fallback strategies.

        Tries in order:
          1. Direct json.loads
          2. Extract from ```json code fences
          3. Regex extraction of first JSON object
        """
        # Try direct parse
        try:
            return json.loads(content.strip("content="))
        except (json.JSONDecodeError, ValueError):
            pass

        # Try ```json code fence
        if "```json" in content:
            try:
                return json.loads(
                    content.split("```")[1].strip("```").strip("json").strip()
                )
            except (json.JSONDecodeError, ValueError, IndexError):
                pass

        # Regex fallback: extract first JSON object or array
        match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', content)
        if match:
            return json.loads(match.group())

        raise ValueError(f"Could not extract JSON from LLM output: {content[:200]}")

    def _graph_documents_to_dict(
        self, graph_documents: List[GraphDocument]
    ) -> Dict[str, List[Dict[str, str]]]:
        """Normalize GraphDocument output into the dict shape used by ingestion/retrieval.

        The rest of the repo expects:
          {
            "nodes": [{"id", "type", "definition"}],
            "rels":  [{"source", "target", "type", "definition"}]
          }
        """
        nodes_dict: Dict[str, Dict[str, str]] = {}
        rels_dict: Dict[tuple, Dict[str, str]] = {}

        for graph_document in graph_documents:
            for node in graph_document.nodes:
                node_id = str(node.id)
                node_type = str(node.type)
                definition = str(node.properties.get("description", "")).strip()
                
                if node_id in nodes_dict:
                    existing_def = nodes_dict[node_id]["definition"]
                    if definition and definition not in existing_def:
                        nodes_dict[node_id]["definition"] = f"{existing_def} | {definition}".strip(" |")
                else:
                    nodes_dict[node_id] = {
                        "id": node_id,
                        "type": node_type,
                        "definition": definition,
                    }

            for rel in graph_document.relationships:
                source = str(rel.source.id)
                target = str(rel.target.id)
                rel_type = str(rel.type)
                definition = str(rel.properties.get("description", "")).strip()
                rel_key = (source, target, rel_type)
                
                if rel_key in rels_dict:
                    existing_def = rels_dict[rel_key]["definition"]
                    if definition and definition not in existing_def:
                        rels_dict[rel_key]["definition"] = f"{existing_def} | {definition}".strip(" |")
                else:
                    rels_dict[rel_key] = {
                        "source": source,
                        "target": target,
                        "type": rel_type,
                        "definition": definition,
                    }

        return {"nodes": list(nodes_dict.values()), "rels": list(rels_dict.values())}

    def _normalize_type(self, t: str) -> str:
        return str(t).replace(" ", "_").lower()

    def _resolve_min_request_interval_seconds(self) -> float:
        config = getattr(self.llm_service, "config", {}) or {}
        configured = config.get("min_request_interval_seconds")
        if configured is None:
            configured = config.get("model_kwargs", {}).get(
                "min_request_interval_seconds"
            )
        if configured is not None:
            try:
                return max(0.0, float(configured))
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid min_request_interval_seconds=%r; using provider default.",
                    configured,
                )

        provider = str(config.get("llm_service", "")).lower()
        model_name = str(config.get("llm_model", "")).lower()
        if provider == "genai" and "gemini-3.1-flash-lite" in model_name:
            # Gemini free-tier requests are low enough that bursty chunk extraction
            # easily trips quota. Keep a local fallback only when the provider
            # does not expose its own shared limiter.
            return 4.25
        return 0.0

    def _uses_provider_rate_limiter(self) -> bool:
        return bool(getattr(self.llm_service, "uses_shared_rate_limiter", False))

    def _wait_for_request_slot(self, payload: Dict[str, Any] | None = None) -> None:
        if self._uses_provider_rate_limiter():
            self.llm_service.wait_for_request_slot(payload)
            return

        if self._min_request_interval_seconds <= 0:
            return

        now = time.monotonic()
        earliest_start = (
            self._last_async_request_started_at + self._min_request_interval_seconds
        )
        if earliest_start > now:
            time.sleep(earliest_start - now)
            now = time.monotonic()
        self._last_async_request_started_at = now

    async def _await_async_request_slot(
        self, payload: Dict[str, Any] | None = None
    ) -> None:
        if self._uses_provider_rate_limiter():
            await self.llm_service.await_rate_limit_slot(payload)
            return

        if self._min_request_interval_seconds <= 0:
            return

        async with self._async_request_lock:
            now = time.monotonic()
            earliest_start = (
                self._last_async_request_started_at + self._min_request_interval_seconds
            )
            if earliest_start > now:
                await asyncio.sleep(earliest_start - now)
                now = time.monotonic()
            self._last_async_request_started_at = now

    def _graph_document_payload_counts(
        self, graph_documents: List[GraphDocument]
    ) -> tuple[int, int, int]:
        doc_count = 0
        node_count = 0
        relationship_count = 0

        for graph_document in graph_documents:
            if not hasattr(graph_document, "nodes") or not hasattr(
                graph_document, "relationships"
            ):
                continue
            doc_count += 1
            node_count += len(graph_document.nodes)
            relationship_count += len(graph_document.relationships)

        return doc_count, node_count, relationship_count

    def _is_empty_graph_documents(self, graph_documents: List[GraphDocument]) -> bool:
        _, node_count, relationship_count = self._graph_document_payload_counts(
            graph_documents
        )
        return node_count == 0 and relationship_count == 0

    def _looks_suspiciously_empty(self, doc_text: str) -> bool:
        stripped = doc_text.strip()
        if len(stripped) < self.suspicious_empty_min_chars:
            return False

        relation_keywords = re.search(
            r"\b("
            r"father|mother|son|daughter|wife|wives|husband|brother|sister|"
            r"offspring|lineage|descended|ancestor|parent|child|children|"
            r"married|begot|born|requested|request|instructed|instruction|"
            r"ordered|asked|caused|cause|because|through|injunctions?"
            r")\b",
            stripped,
            flags=re.IGNORECASE,
        )
        if relation_keywords:
            return True

        titlecase_tokens = re.findall(r"\b[A-Z][A-Za-z-]{2,}\b", stripped)
        return len(titlecase_tokens) >= 4

    def _should_retry_empty_extraction(
        self,
        doc_text: str,
        graph_documents: List[GraphDocument],
        extra_instruction: str | None,
    ) -> bool:
        return (
            extra_instruction is None
            and self.empty_extraction_retries > 0
            and self._is_empty_graph_documents(graph_documents)
            and self._looks_suspiciously_empty(doc_text)
        )

    def _build_prompt_messages(
        self, extra_instruction: str | None = None
    ) -> list[tuple[str, str]]:
        prompt = [
            ("system", self.llm_service.entity_relationship_extraction_prompt),
            (
                "human",
                "Tip: Make sure to answer in the correct format and do "
                "not include any explanations. "
                "Use the given format to extract information from the "
                "following input: {input}",
            ),
            (
                "human",
                "Mandatory: Make sure to answer in the correct format, specified here: {format_instructions}",
            ),
        ]
        if self.allowed_vertex_types or self.allowed_edge_types:
            prompt.append(
                (
                    "human",
                    "Tip: Make sure to use the following types if they are applicable. "
                    "If the input does not contain any of the types, you may create your own.",
                )
            )
        if self.allowed_vertex_types:
            prompt.append(("human", f"Allowed Node Types: {self.allowed_vertex_types}"))
        if self.allowed_edge_types:
            prompt.append(("human", f"Allowed Edge Types: {self.allowed_edge_types}"))
        if extra_instruction:
            prompt.append(("human", extra_instruction))
        return prompt

    def _json_to_graph_document(
        self, json_out: Dict[str, Any], doc: str
    ) -> List[GraphDocument]:
        if isinstance(json_out, KnowledgeGraph):
            kg = json_out
        else:
            payload = json_out.model_dump() if hasattr(json_out, "model_dump") else json_out
            kg = KnowledgeGraph.model_validate(payload)

        formatted_rels = []
        for rels in kg.rels:
            formatted_rels.append(
                {
                    "source": rels.source.id,
                    "target": rels.target.id,
                    "type": rels.relation_type.replace(" ", "_"),
                    "definition": rels.definition,
                }
            )

        formatted_nodes = []
        for node in kg.nodes:
            formatted_nodes.append(
                {
                    "id": node.id,
                    "type": node.node_type.replace(" ", "_"),
                    "definition": node.definition,
                }
            )

        if self.strict_mode:
            if self.allowed_vertex_types:
                normalized_allowed = {self._normalize_type(t) for t in self.allowed_vertex_types}
                formatted_nodes = [
                    node
                    for node in formatted_nodes
                    if self._normalize_type(node["type"]) in normalized_allowed
                ]
            if self.allowed_edge_types:
                normalized_allowed = {self._normalize_type(t) for t in self.allowed_edge_types}
                formatted_rels = [
                    rel
                    for rel in formatted_rels
                    if self._normalize_type(rel["type"]) in normalized_allowed
                ]

            # Filter out dangling edges
            valid_node_ids = {n["id"] for n in formatted_nodes}
            formatted_rels = [
                rel for rel in formatted_rels
                if rel["source"] in valid_node_ids and rel["target"] in valid_node_ids
            ]

        nodes = []
        node_type_map = {}
        for node in formatted_nodes:
            node_type_map[node["id"]] = node["type"]
            nodes.append(
                Node(
                    id=node["id"],
                    type=node["type"],
                    properties={"description": node["definition"]},
                )
            )
            
        relationships = []
        for rel in formatted_rels:
            source_type = node_type_map.get(rel["source"], "Unknown")
            target_type = node_type_map.get(rel["target"], "Unknown")
            relationships.append(
                Relationship(
                    source=Node(
                        id=rel["source"],
                        type=source_type,
                    ),
                    target=Node(
                        id=rel["target"],
                        type=target_type,
                    ),
                    type=rel["type"],
                    properties={"description": rel["definition"]},
                )
            )

        return self._empty_graph_document(doc) if not nodes and not relationships else [
            GraphDocument(
                nodes=nodes,
                relationships=relationships,
                source=Document(page_content=doc),
            )
        ]

    async def _aextract_kg_from_doc(self, doc, chain, parser) -> list[GraphDocument]:
        doc_text = self._coerce_text(doc)
        logger.debug(doc_text)
        payload = {
            "input": doc_text,
            "format_instructions": parser.get_format_instructions(),
        }
        await self._await_async_request_slot(payload)
        out = await chain.ainvoke(payload)
        logger.debug(str(out))
        json_out = self._parse_json_output(out.content)
        return self._json_to_graph_document(json_out, doc_text)

    def _extract_kg_from_doc(self, doc, chain, parser) -> list[GraphDocument]:
        doc_text = self._coerce_text(doc)
        payload = {
            "input": doc_text,
            "format_instructions": parser.get_format_instructions(),
        }
        self._wait_for_request_slot(payload)
        out = chain.invoke(payload)
        json_out = self._parse_json_output(out.content)
        return self._json_to_graph_document(json_out, doc_text)

    async def _arun_graph_documents(
        self, document, extra_instruction: str | None = None
    ):
        from langchain.prompts import ChatPromptTemplate
        from langchain.output_parsers import PydanticOutputParser

        parser = PydanticOutputParser(pydantic_object=KnowledgeGraph)
        prompt = ChatPromptTemplate.from_messages(
            self._build_prompt_messages(extra_instruction)
        )
        doc_text = self._coerce_text(document)

        if hasattr(self.llm_service.llm, "with_structured_output"):
            structured_llm = self.llm_service.llm.with_structured_output(KnowledgeGraph)
            chain = prompt | structured_llm
            try:
                payload = {"input": doc_text, "format_instructions": ""}
                await self._await_async_request_slot(payload)
                out = await chain.ainvoke(payload)
                json_out = out.model_dump() if hasattr(out, "model_dump") else out
                er = self._json_to_graph_document(json_out, doc_text)
            except Exception as e:
                logger.warning(f"Structured async extraction failed: {e}. Falling back to text parsing.")
                chain = prompt | self.llm_service.llm
                er = await self._aextract_kg_from_doc(document, chain, parser)
        else:
            chain = prompt | self.llm_service.llm
            er = await self._aextract_kg_from_doc(document, chain, parser)

        return er

    async def _adocument_er_graph_documents(
        self, document, extra_instruction: str | None = None
    ):
        doc_text = self._coerce_text(document)
        er = await self._arun_graph_documents(document, extra_instruction)

        if self._should_retry_empty_extraction(doc_text, er, extra_instruction):
            logger.warning(
                "Primary extraction returned a valid schema but zero entities/relationships. "
                "Retrying focused fallback extraction."
            )
            return await self._adocument_er_graph_documents(
                document,
                extra_instruction=self.EMPTY_EXTRACTION_FALLBACK_INSTRUCTION,
            )
        return er

    async def adocument_er_graph_documents(self, document):
        return await self._adocument_er_graph_documents(document)

    def _run_graph_documents(
        self, document, extra_instruction: str | None = None
    ):
        from langchain.prompts import ChatPromptTemplate
        from langchain.output_parsers import PydanticOutputParser

        parser = PydanticOutputParser(pydantic_object=KnowledgeGraph)
        prompt = ChatPromptTemplate.from_messages(
            self._build_prompt_messages(extra_instruction)
        )
        doc_text = self._coerce_text(document)

        if hasattr(self.llm_service.llm, "with_structured_output"):
            structured_llm = self.llm_service.llm.with_structured_output(KnowledgeGraph)
            chain = prompt | structured_llm
            try:
                payload = {"input": doc_text, "format_instructions": ""}
                self._wait_for_request_slot(payload)
                out = chain.invoke(payload)
                json_out = out.model_dump() if hasattr(out, "model_dump") else out
                er = self._json_to_graph_document(json_out, doc_text)
            except Exception as e:
                logger.warning(f"Structured extraction failed: {e}. Falling back to text parsing.")
                chain = prompt | self.llm_service.llm
                er = self._extract_kg_from_doc(document, chain, parser)
        else:
            chain = prompt | self.llm_service.llm
            er = self._extract_kg_from_doc(document, chain, parser)

        return er

    def _document_er_graph_documents(
        self, document, extra_instruction: str | None = None
    ):
        doc_text = self._coerce_text(document)
        er = self._run_graph_documents(document, extra_instruction)

        if self._should_retry_empty_extraction(doc_text, er, extra_instruction):
            logger.warning(
                "Primary extraction returned a valid schema but zero entities/relationships. "
                "Retrying focused fallback extraction."
            )
            return self._document_er_graph_documents(
                document,
                extra_instruction=self.EMPTY_EXTRACTION_FALLBACK_INSTRUCTION,
            )
        return er

    def document_er_graph_documents(self, document):
        return self._document_er_graph_documents(document)

    async def adocument_er_extraction(self, document):
        er = await self.adocument_er_graph_documents(document)
        return self._graph_documents_to_dict(er)

    def document_er_extraction(self, document):
        er = self.document_er_graph_documents(document)
        return self._graph_documents_to_dict(er)

    def extract(self, text):
        return self.document_er_extraction(text)
    
    async def aextract(self, text):
        return await self._adocument_er_graph_documents(text)
    

