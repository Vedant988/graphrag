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

import ast
import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator
from langchain_community.graphs.graph_document import Node as BaseNode
from langchain_community.graphs.graph_document import Relationship as BaseRelationship


def _coerce_properties(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped in {"{}", "null", "None"}:
            return {}
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(stripped)
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return {"description": stripped}
    return {}


def _normalize_node_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, str):
        return {
            "id": value,
            "type": "Unknown",
            "node_type": "Unknown",
            "definition": "",
            "properties": {},
        }
    if not isinstance(value, dict):
        return value

    node = dict(value)
    node["properties"] = _coerce_properties(node.get("properties"))
    if not node.get("type") and node.get("node_type"):
        node["type"] = node["node_type"]
    if not node.get("node_type") and node.get("type"):
        node["node_type"] = node["type"]
    if not node.get("definition"):
        node["definition"] = (
            node["properties"].get("description")
            or node["properties"].get("definition")
            or node.get("description", "")
        )
    if not node.get("evidence"):
        node["evidence"] = (
            node["properties"].get("evidence")
            or node.get("supporting_text", "")
        )
    return node


def _normalize_relationship_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        return value

    rel = dict(value)
    rel["properties"] = _coerce_properties(rel.get("properties"))
    if not rel.get("type") and rel.get("relation_type"):
        rel["type"] = rel["relation_type"]
    if not rel.get("relation_type") and rel.get("type"):
        rel["relation_type"] = rel["type"]
    if not rel.get("definition"):
        rel["definition"] = (
            rel["properties"].get("description")
            or rel["properties"].get("definition")
            or rel.get("description", "")
        )
    if not rel.get("evidence"):
        rel["evidence"] = (
            rel["properties"].get("evidence")
            or rel.get("supporting_text", "")
        )
    if "source" in rel:
        rel["source"] = _normalize_node_payload(rel["source"])
    if "target" in rel:
        rel["target"] = _normalize_node_payload(rel["target"])
    return rel


class MapQuestionToSchemaResponse(BaseModel):
    question: str = Field(
        description="The question restated in terms of the graph schema"
    )
    target_vertex_types: List[str] = Field(
        description="The list of vertices mentioned in the question. If there are no vertices mentioned, then use an empty list."
    )
    target_vertex_attributes: Optional[Dict[str, List[str]]] = Field(
        description="The dictionary of vertex attributes mentioned in the question, formated in {'vertex_type_1': ['vertex_attribute_1', 'vertex_attribute_2'], 'vertex_type_2': ['vertex_attribute_1', 'vertex_attribute_2']}"
    )
    target_vertex_ids: Optional[Dict[str, List[str]]] = Field(
        description="The dictionary of vertex ids mentioned in the question. If there are no vertex ids mentioned, then use an empty dict. formated in {'vertex_type_1': ['vertex_id_1', 'vertex_id_2'], 'vertex_type_2': ['vertex_id_1', 'vertex_id_2']}"
    )
    target_edge_types: Optional[List[str]] = Field(
        description="The list of edges mentioned in the question"
    )
    target_edge_attributes: Optional[Dict[str, List[str]]] = Field(
        description="The dictionary of edge attributes mentioned in the question, formated in {'edge_type': ['edge_attribute_1', 'edge_attribute_2']}"
    )


class AgentOutput(BaseModel):
    answer: str = Field(description="Natural language answer generated")
    function_call: str = Field(description="Function call used to generate answer")


class MapAttributeToAttributeResponse(BaseModel):
    attr_map: Optional[Dict[str, str]] = Field(
        description="The dictionary of the form {'source_attribute': 'output_attribute'}"
    )


class GenerateFunctionResponse(BaseModel):
    connection_func_call: str = Field(
        description="The function call to make to answer the question. Must start with conn."
    )
    func_call_reasoning: str = Field(
        description="The reason why the function call was generated to answer the question."
    )


class Node(BaseNode):
    @model_validator(mode="before")
    @classmethod
    def normalize_node(cls, value):
        return _normalize_node_payload(value)

    node_type: str = Field(
        description="Type of the node. Use the most specific stable type grounded in the text, such as Person, Warrior, Sage, Deity, RoyalFigure, Group, Place, Event, TextWork, Artifact, Lineage, or Concept."
    )
    definition: str = Field(
        description="Normalized factual description of what the entity is in the context of the passage."
    )
    evidence: Optional[str] = Field(
        default=None,
        description="Short grounded evidence span from the passage supporting this node."
    )


class Relationship(BaseRelationship):
    @model_validator(mode="before")
    @classmethod
    def normalize_relationship(cls, value):
        return _normalize_relationship_payload(value)

    relation_type: str = Field(
        description="Canonical reusable relationship type in uppercase with underscores, such as FATHERED, ENJOINED, MENTORED, AUTHORED, SLAIN_BY, LOCATED_IN, or CAUSED. Preserve accuracy without inventing brittle one-off types when a canonical verb works."
    )
    source: Node = Field(description="The source node of the relationship.")
    target: Node = Field(description="The target node of the relationship.")
    definition: str = Field(
        description="Normalized factual description of who did what to whom, and why or in what context if the passage provides it."
    )
    evidence: Optional[str] = Field(
        default=None,
        description="Short grounded evidence span from the passage supporting this relationship."
    )


class KnowledgeGraph(BaseModel):
    """Generate a knowledge graph with entities and relationships."""

    nodes: List[Node] = Field(..., description="List of nodes in the knowledge graph")
    rels: List[Relationship] = Field(
        ..., description="List of relationships in the knowledge graph"
    )


class ReportQuestion(BaseModel):
    question: str = Field("The question to be asked")
    reasoning: str = Field("The reasoning behind the question")


class ReportSection(BaseModel):
    section: str = Field("Name of the section")
    description: str = Field("Description of the section")
    questions: List[ReportQuestion] = Field(
        "List of questions and reasoning for the section"
    )


class ReportSections(BaseModel):
    sections: List[ReportSection] = Field("List of sections for the report")


class CommunitySummary(BaseModel):
    """Generate a summary of the documents that are within this community."""

    summary: str = Field(
        ..., description="The community summary derived from the input documents"
    )

class GraphRAGAnswerOutput(BaseModel):
    generated_answer: str = Field(description="The generated answer to the question. Make sure maintain a professional tone.")
    citation: Optional[list[str]] = Field(description="The citation for the answer. List the metadata, mostly the keys, of the parts of the context used.", default=[])


class CandidateScore(BaseModel):
    candidate: str = Field(description="The candidate answer according to the prompt.")
    quality_score: int = Field(description="The quality of the candidate answer, based on how well it meets the requirement in the prompt. Rate the candidate from 0 (poor) to 100 (excellent).")


class CandidateGenerator(BaseModel):
    candidates: List[CandidateScore] = Field(..., description="List of candidate questions with quality scores")

class CommunityAnswer(BaseModel):
    answer: str = Field(description="The answer to the question, based off of the context provided.")
    quality_score: int = Field(description="The quality of the answer, based on how well it answers the question. Rate the answer from 0 (poor) to 100 (excellent).")
