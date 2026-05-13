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

import logging
import re
from typing import Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field, field_validator

from common.logs.log import req_id_cv
from common.logs.logwriter import LogWriter

logger = logging.getLogger(__name__)


class RetrievalRouteResponse(BaseModel):
    route: str = Field(description="The retrieval strategy. Must be GRAPH or VECTOR.")

    @field_validator("route", mode="before")
    @classmethod
    def normalize_route(cls, value):
        normalized = str(value).strip().upper()
        if normalized not in {"GRAPH", "VECTOR"}:
            raise ValueError("route must be GRAPH or VECTOR")
        return normalized


class RetrievalRouteDecision(BaseModel):
    route: str
    source: str
    reason: str


class GraphRetrievalProfileDecision(BaseModel):
    name: str
    reason: str
    top_k: int
    num_hops: int
    num_seen_min: int
    similarity_threshold: float = 0.90
    chunk_only: bool = True
    doc_only: bool = False
    combine: bool = False
    max_score_candidates: int


class TigerGraphSupportAIRouter:
    """Router that chooses between vector retrieval and graph retrieval."""

    _GRAPH_PATTERNS = (
        (re.compile(r"\bhow are (they|these|those)\b"), "explicit_connection_request"),
        (re.compile(r"\bconnected?\b"), "explicit_connection_request"),
        (re.compile(r"\brelationship between\b"), "explicit_relationship_request"),
        (re.compile(r"\bshortest path\b"), "path_finding_request"),
        (re.compile(r"\bpath between\b"), "path_finding_request"),
        (re.compile(r"\btrace\b"), "trace_request"),
        (re.compile(r"\blineage\b"), "lineage_request"),
        (re.compile(r"\bmentorship\b"), "mentorship_request"),
        (re.compile(r"\bmentor(?:ed|ship)?\b"), "mentorship_request"),
        (re.compile(r"\bancestr(?:y|al)\b"), "ancestry_request"),
        (re.compile(r"\bfamily tree\b"), "ancestry_request"),
        (re.compile(r"\broot causes?\b"), "cross_chunk_aggregation"),
        (re.compile(r"\baggregate\b"), "aggregation_request"),
        (re.compile(r"\bthemes?\b"), "theme_aggregation"),
        (re.compile(r"\bjustifications?\b"), "theme_aggregation"),
        (re.compile(r"\bacross (?:the )?(?:entire|all|different)\b"), "cross_document_scope"),
        (re.compile(r"\bacross (?:pages?|chapters?|documents?)\b"), "cross_document_scope"),
        (re.compile(r"\bthroughout (?:the )?(?:text|document|corpus)\b"), "cross_document_scope"),
        (re.compile(r"\blist (?:all|every)\b"), "large_list_request"),
        (re.compile(r"\bcount (?:all|every)\b"), "large_list_request"),
        (re.compile(r"\bhow many different\b"), "large_list_request"),
        (re.compile(r"\bmassive loss of life\b"), "cross_chunk_aggregation"),
    )

    _VECTOR_PATTERNS = (
        re.compile(r"^(who|what|when|where|which)\b"),
        re.compile(r"^(identify|name|describe|summarize)\b"),
    )

    _AGGREGATION_PATTERNS = (
        (re.compile(r"\broot causes?\b"), "cross_chunk_aggregation"),
        (re.compile(r"\baggregate\b"), "aggregation_request"),
        (re.compile(r"\bthemes?\b"), "theme_aggregation"),
        (re.compile(r"\bjustifications?\b"), "theme_aggregation"),
        (re.compile(r"\bacross (?:the )?(?:entire|all|different)\b"), "cross_document_scope"),
        (re.compile(r"\bacross (?:pages?|chapters?|documents?)\b"), "cross_document_scope"),
        (re.compile(r"\bthroughout (?:the )?(?:text|document|corpus)\b"), "cross_document_scope"),
        (re.compile(r"\blist (?:all|every)\b"), "large_list_request"),
        (re.compile(r"\bcount (?:all|every)\b"), "large_list_request"),
        (re.compile(r"\bhow many different\b"), "large_list_request"),
        (re.compile(r"\bmassive loss of life\b"), "cross_chunk_aggregation"),
    )

    _RELATION_PATTERNS = (
        (re.compile(r"\bhow are (they|these|those)\b"), "explicit_connection_request"),
        (re.compile(r"\bconnected?\b"), "explicit_connection_request"),
        (re.compile(r"\brelationship between\b"), "explicit_relationship_request"),
        (re.compile(r"\bshortest path\b"), "path_finding_request"),
        (re.compile(r"\bpath between\b"), "path_finding_request"),
        (re.compile(r"\btrace\b"), "trace_request"),
        (re.compile(r"\blineage\b"), "lineage_request"),
        (re.compile(r"\bmentorship\b"), "mentorship_request"),
        (re.compile(r"\bmentor(?:ed|ship)?\b"), "mentorship_request"),
        (re.compile(r"\bancestr(?:y|al)\b"), "ancestry_request"),
        (re.compile(r"\bfamily tree\b"), "ancestry_request"),
    )

    _GRAPH_HINT_WORDS = {
        "aggregate",
        "aggregated",
        "across",
        "chain",
        "connect",
        "connected",
        "connection",
        "count",
        "different",
        "lineage",
        "list",
        "mentorship",
        "path",
        "reasons",
        "relationship",
        "themes",
        "trace",
    }

    def __init__(self, llm_model):
        self.llm = llm_model

    @staticmethod
    def _normalize_question(question: str) -> str:
        return re.sub(r"\s+", " ", question.strip())

    def _heuristic_route(self, question: str) -> Optional[RetrievalRouteDecision]:
        normalized = self._normalize_question(question)
        lowered = normalized.lower()

        for pattern, reason in self._GRAPH_PATTERNS:
            if pattern.search(lowered):
                return RetrievalRouteDecision(
                    route="GRAPH",
                    source="heuristic",
                    reason=reason,
                )

        word_count = len(lowered.split())
        has_graph_hint = any(hint in lowered for hint in self._GRAPH_HINT_WORDS)
        if word_count <= 16 and not has_graph_hint:
            for pattern in self._VECTOR_PATTERNS:
                if pattern.search(lowered):
                    return RetrievalRouteDecision(
                        route="VECTOR",
                        source="heuristic",
                        reason="simple_lookup_pattern",
                    )

        return None

    def route_question(self, question: str) -> RetrievalRouteDecision:
        LogWriter.info(
            f"request_id={req_id_cv.get()} ENTRY route_supportai_retrieval with {question}"
        )

        heuristic_decision = self._heuristic_route(question)
        if heuristic_decision is not None:
            LogWriter.info(
                f"request_id={req_id_cv.get()} EXIT route_supportai_retrieval "
                f"with heuristic decision {heuristic_decision.model_dump()}"
            )
            return heuristic_decision

        router_parser = PydanticOutputParser[RetrievalRouteResponse](
            pydantic_object=RetrievalRouteResponse
        )
        prompt = PromptTemplate(
            template=self.llm.retrieval_router_prompt,
            input_variables=["question"],
            partial_variables={
                "format_instructions": router_parser.get_format_instructions()
            },
        )
        response = self.llm.invoke_with_parser(
            prompt,
            router_parser,
            {"question": question},
            caller_name="route_supportai_retrieval",
        )

        decision = RetrievalRouteDecision(
            route=response.route,
            source="llm",
            reason="llm_classifier",
        )
        LogWriter.info(
            f"request_id={req_id_cv.get()} EXIT route_supportai_retrieval "
            f"with llm decision {decision.model_dump()}"
        )
        return decision

    def graph_profile_for_question(self, question: str) -> GraphRetrievalProfileDecision:
        normalized = self._normalize_question(question)
        lowered = normalized.lower()

        for pattern, reason in self._AGGREGATION_PATTERNS:
            if pattern.search(lowered):
                return GraphRetrievalProfileDecision(
                    name="aggregation_graph",
                    reason=reason,
                    top_k=4,
                    num_hops=2,
                    num_seen_min=2,
                    similarity_threshold=0.90,
                    chunk_only=True,
                    doc_only=False,
                    combine=False,
                    max_score_candidates=4,
                )

        for pattern, reason in self._RELATION_PATTERNS:
            if pattern.search(lowered):
                return GraphRetrievalProfileDecision(
                    name="relation_graph",
                    reason=reason,
                    top_k=5,
                    num_hops=2,
                    num_seen_min=1,
                    similarity_threshold=0.90,
                    chunk_only=False,
                    doc_only=False,
                    combine=False,
                    max_score_candidates=5,
                )

        return GraphRetrievalProfileDecision(
            name="factoid_graph",
            reason="lightweight_factoid_lookup",
            top_k=2,
            num_hops=1,
            num_seen_min=1,
            similarity_threshold=0.92,
            chunk_only=True,
            doc_only=False,
            combine=False,
            max_score_candidates=2,
        )
