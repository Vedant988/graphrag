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

import json
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security.http import HTTPBase
from agent.retrieval_router import TigerGraphSupportAIRouter
from supportai import supportai
from supportai.retrievers import (
    EntityRelationshipRetriever,
    HybridRetriever,
    SimilarityRetriever,
    SiblingRetriever,
    CommunityRetriever
)

from common.config import (
    db_config,
    graphrag_config,
    embedding_service,
    embedding_store,
    get_chat_config,
    get_llm_service,
    service_status,
)
from common.logs.logwriter import LogWriter
from common.py_schemas.schemas import (  # SupportAIInitConfig,; SupportAIMethod,
    GraphRAGResponse,
    CreateIngestConfig,
    LoadingInfo,
    SupportAIMethod,
    SupportAIQuestion,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["SupportAI"])

security = HTTPBase(scheme="basic", auto_error=False)

_AUTO_ROUTER_METHODS = {"auto", "autorouter", "autorag"}


def check_embedding_store_status():
    if service_status["embedding_store"]["error"]:
        return HTTPException(
            status_code=503, detail=service_status["embedding_store"]["error"]
        )


def _resolve_supportai_method(method: str, question: str, llm_service) -> tuple[str, dict | None]:
    normalized = (method or "").lower().replace(" ", "")
    if normalized not in _AUTO_ROUTER_METHODS:
        return normalized, None

    router = TigerGraphSupportAIRouter(llm_service)
    try:
        decision = router.route_question(question).model_dump()
        if decision["route"] == "GRAPH":
            decision["graph_profile"] = router.graph_profile_for_question(question).model_dump()
    except Exception as exc:
        decision = {
            "route": "GRAPH",
            "source": "fallback",
            "reason": f"router_error:{exc}",
        }
        try:
            decision["graph_profile"] = router.graph_profile_for_question(question).model_dump()
        except Exception:
            pass
    resolved = "hybrid" if decision["route"] == "GRAPH" else "similarity"
    logger.info("Auto router resolved supportai method to %s with %s", resolved, decision)
    return resolved, decision


def _apply_auto_router_defaults(query: SupportAIQuestion, method: str, router_decision: dict | None) -> None:
    if not router_decision:
        return

    graph_profile = router_decision.get("graph_profile") or {}
    query.method_params.setdefault("top_k", graph_profile.get("top_k", 5))
    if method == "similarity":
        query.method_params.setdefault("index", "DocumentChunk")
        query.method_params.setdefault("withHyDE", False)
    elif method == "hybrid":
        query.method_params.setdefault("indices", ["DocumentChunk"])
        query.method_params.setdefault(
            "similarity_threshold",
            graph_profile.get("similarity_threshold", 0.90),
        )
        query.method_params.setdefault("num_hops", graph_profile.get("num_hops", 2))
        query.method_params.setdefault(
            "num_seen_min",
            graph_profile.get("num_seen_min", 2),
        )
        query.method_params.setdefault("method", "similarity")
        query.method_params.setdefault(
            "chunk_only",
            graph_profile.get("chunk_only", True),
        )
        query.method_params.setdefault(
            "doc_only",
            graph_profile.get("doc_only", False),
        )
        query.method_params.setdefault(
            "combine",
            graph_profile.get("combine", False),
        )
        query.method_params.setdefault(
            "max_score_candidates",
            graph_profile.get("max_score_candidates"),
        )


def _attach_router_decision(result: dict, router_decision: dict | None) -> dict:
    if not router_decision:
        return result

    result["router_decision"] = router_decision
    retrieved = result.get("retrieved")
    if isinstance(retrieved, dict):
        retrieved["router_decision"] = router_decision
    return result


@router.post("/{graphname}/graphrag/initialize")
@router.post("/{graphname}/supportai/initialize")
def initialize(
    graphname,
    conn: Request,
    credentials: Annotated[HTTPBase, Depends(security)],
):
    conn = conn.state.conn

    resp = supportai.init_supportai(conn, graphname)
    schema_res, index_res, query_res = resp[0], resp[1], resp[2]
    return {
        "host_name": conn._tg_connection.host,  # include host_name for debugging from client. Their pyTG conn might not have the same host as what's configured in graphrag
        "schema_creation_status": json.dumps(schema_res),
        "index_creation_status": json.dumps(index_res),
        "query_creation_status": json.dumps(query_res),
    }


@router.post("/{graphname}/graphrag/create_ingest")
@router.post("/{graphname}/supportai/create_ingest")
def create_ingest(
    graphname,
    cfg: CreateIngestConfig,
    conn: Request,
    credentials: Annotated[HTTPBase, Depends(security)],
):
    conn = conn.state.conn

    return supportai.create_ingest(graphname, cfg, conn)


@router.post("/{graphname}/graphrag/ingest")
@router.post("/{graphname}/supportai/ingest")
def ingest(
    graphname,
    loader_info: LoadingInfo,
    conn: Request,
    credentials: Annotated[HTTPBase, Depends(security)],
):
    conn = conn.state.conn

    return supportai.ingest(graphname, loader_info, conn)


@router.post("/{graphname}/graphrag/search")
@router.post("/{graphname}/supportai/search")
def search(
    graphname,
    query: SupportAIQuestion,
    conn: Request,
    credentials: Annotated[HTTPBase, Depends(security)],
):
    check_embedding_store_status()
    conn = conn.state.conn
    llm_service = get_llm_service(get_chat_config(graphname))
    method, router_decision = _resolve_supportai_method(
        query.method, query.question, llm_service
    )
    _apply_auto_router_defaults(query, method, router_decision)
    if "expand" not in query.method_params:
        query.method_params["expand"] = False
    if "verbose" not in query.method_params:
        query.method_params["verbose"] = False
    if method == "hybrid":
        retriever = HybridRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        if "method" not in query.method_params:
            query.method_params["method"] = "similarity"
        if "chunk_only" not in query.method_params:
            query.method_params["chunk_only"] = False
        if "doc_only" not in query.method_params:
            query.method_params["doc_only"] = False
        if "similarity_threshold" not in query.method_params:
            query.method_params["similarity_threshold"] = 0.90
        res = retriever.search(
            query.question,
            query.method_params["indices"],
            query.method_params["top_k"],
            query.method_params["similarity_threshold"],
            query.method_params["num_hops"],
            query.method_params["num_seen_min"],
            query.method_params["expand"],
            query.method_params["method"],
            query.method_params["chunk_only"],
            query.method_params["doc_only"],
            query.method_params["verbose"],
        )
    elif method == "similarity":
        if "index" not in query.method_params:
            raise Exception("Index name not provided")
        retriever = SimilarityRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        res = retriever.search(
            query.question,
            query.method_params["index"],
            query.method_params["top_k"],
            query.method_params["withHyDE"],
            query.method_params["expand"],
            query.method_params["verbose"],
        )
    elif method == "contextual":
        if "index" not in query.method_params:
            raise Exception("Index name not provided")
        retriever = SiblingRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        res = retriever.search(
            query.question,
            query.method_params["index"],
            query.method_params["top_k"],
            query.method_params["lookback"],
            query.method_params["lookahead"],
            query.method_params["withHyDE"],
            query.method_params["expand"],
            query.method_params["verbose"],
        )
    elif method == "entityrelationship":
        retriever = EntityRelationshipRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        res = retriever.search(query.question, query.method_params["top_k"])
    elif method == "community":
        retriever = CommunityRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        if "with_chunk" not in query.method_params:
            query.method_params["with_chunk"] = True
        if "with_doc" not in query.method_params:
            query.method_params["with_doc"] = False
        if "similarity_threshold" not in query.method_params:
            query.method_params["similarity_threshold"] = 0.90
        res = retriever.search(
            query.question,
            query.method_params["community_level"],
            query.method_params["top_k"],
            query.method_params["similarity_threshold"],
            query.method_params["expand"],
            query.method_params["with_chunk"],
            query.method_params["with_doc"],
            query.method_params["verbose"],
        )
    else:
        raise Exception(f"Method {query.method} not implemented")
    return _attach_router_decision(res, router_decision)


@router.post("/{graphname}/graphrag/answerquestion")
@router.post("/{graphname}/supportai/answerquestion")
def answer_question(
    graphname,
    query: SupportAIQuestion,
    conn: Request,
    credentials: Annotated[HTTPBase, Depends(security)],
):
    check_embedding_store_status()
    conn = conn.state.conn
    llm_service = get_llm_service(get_chat_config(graphname))
    method, router_decision = _resolve_supportai_method(
        query.method, query.question, llm_service
    )
    _apply_auto_router_defaults(query, method, router_decision)
    resp = GraphRAGResponse
    resp.response_type = "supportai"
    if "combine" not in query.method_params:
        query.method_params["combine"] = False
    if "expand" not in query.method_params:
        query.method_params["expand"] = False
    if "verbose" not in query.method_params:
        query.method_params["verbose"] = False
    if method == "hybrid":
        retriever = HybridRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        if "method" not in query.method_params:
            query.method_params["method"] = "Similarity"
        if "chunk_only" not in query.method_params:
            query.method_params["chunk_only"] = False
        if "doc_only" not in query.method_params:
            query.method_params["doc_only"] = False
        if "similarity_threshold" not in query.method_params:
            query.method_params["similarity_threshold"] = 0.90
        res = retriever.retrieve_answer(
            query.question,
            query.method_params["indices"],
            query.method_params["top_k"],
            query.method_params["similarity_threshold"],
            query.method_params["num_hops"],
            query.method_params["num_seen_min"],
            query.method_params["expand"],
            query.method_params["method"],
            query.method_params["chunk_only"],
            query.method_params["doc_only"],
            query.method_params["combine"],
            query.method_params["verbose"],
            query.method_params.get("max_score_candidates"),
        )
    elif method == "similarity":
        if "index" not in query.method_params:
            raise Exception("Index name not provided")
        retriever = SimilarityRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        res = retriever.retrieve_answer(
            query.question,
            query.method_params["index"],
            query.method_params["top_k"],
            query.method_params["withHyDE"],
            query.method_params["expand"],
            query.method_params["combine"],
            query.method_params["verbose"],
            query.method_params.get("max_score_candidates"),
        )
    elif method == "contextual":
        if "index" not in query.method_params:
            raise Exception("Index name not provided")
        retriever = SiblingRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        res = retriever.retrieve_answer(
            query.question,
            query.method_params["index"],
            query.method_params["top_k"],
            query.method_params["lookback"],
            query.method_params["lookahead"],
            query.method_params["withHyDE"],
            query.method_params["expand"],
            query.method_params["combine"],
            query.method_params["verbose"],
            query.method_params.get("max_score_candidates"),
        )
    elif method == "entityrelationship":
        retriever = EntityRelationshipRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        res = retriever.retrieve_answer(query.question, query.method_params["top_k"])

    elif method == "community":
        retriever = CommunityRetriever(
            embedding_service, embedding_store, llm_service, conn
        )
        if "with_chunk" not in query.method_params:
            query.method_params["with_chunk"] = True
        if "with_doc" not in query.method_params:
            query.method_params["with_doc"] = False
        if "similarity_threshold" not in query.method_params:
            query.method_params["similarity_threshold"] = 0.90
        res = retriever.retrieve_answer(
            query.question,
            query.method_params["community_level"],
            query.method_params["top_k"],
            query.method_params["similarity_threshold"],
            query.method_params["expand"],
            query.method_params["with_chunk"],
            query.method_params["with_doc"],
            query.method_params["combine"],
            query.method_params["verbose"],
            query.method_params.get("max_score_candidates"),
        )
    else:
        raise Exception("Method not implemented")

    res = _attach_router_decision(res, router_decision)
    resp.natural_language_response = res["response"]
    resp.query_sources = res["retrieved"]

    return res


@router.get("/{graphname}/{method}/forceupdate")
def graphrag_update(
    graphname: str,
    method: str,
    conn: Request,
    credentials: Annotated[HTTPBase, Depends(security)],
    bg_tasks: BackgroundTasks,
    response: Response,
):
    if method != SupportAIMethod.SUPPORTAI and method != SupportAIMethod.GRAPHRAG:
        response.status_code = status.HTTP_404_NOT_FOUND
        return f"{method} is not a valid method. {SupportAIMethod.SUPPORTAI} or {SupportAIMethod.GRAPHRAG}"

    from httpx import get as http_get

    ecc = (
        graphrag_config.get("ecc", "http://graphrag-ecc:8001")
        + f"/{graphname}/{method}/consistency_update"
    )
    LogWriter.info(f"Sending ECC request to: {ecc}")
    bg_tasks.add_task(
        http_get, ecc, headers={"Authorization": conn.headers["authorization"]}
    )
    return {"status": "submitted"}


@router.post("/{graphname}/graphrag/create_graph")
def create_graph(
    graphname: str,
    conn: Request,
):
    """
    Create a new TigerGraph knowledge graph.
    This creates an empty graph with the specified name.
    The middleware creates the TigerGraph connection and stores it in request.state.conn
    """
    try:
        # Get the connection from request state (created by auth_middleware in main.py)
        tg_conn = conn.state.conn

        # Create the graph using GSQL
        LogWriter.info(f"Creating graph: {graphname}")
        create_query = f"CREATE GRAPH {graphname}()"
        result = tg_conn.gsql(create_query)

        LogWriter.info(f"Graph creation result: {result}")
        return {
            "status": "success",
            "message": f"Graph '{graphname}' created successfully",
            "graphname": graphname,
            "details": result
        }

    except Exception as e:
        LogWriter.error(f"Error creating graph {graphname}: {str(e)}")
        if "conflicts" in str(e).lower() or "existing graph" in str(e).lower():
            return {
                "status": "error",
                "message": f"Graph '{graphname}' already exists",
                "details": str(e)
            }
        else:
            return {
                "status": "error",
                "message": f"Failed to create graph '{graphname}': {str(e)}",
                "details": str(e)
            }
