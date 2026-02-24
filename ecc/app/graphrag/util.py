# Copyright (c) 2025 TigerGraph, Inc.
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
import base64
import json
import logging
import re
import time
import traceback
from collections import defaultdict
from glob import glob

import httpx
from graphrag import reusable_channel, workers
from pyTigerGraph import AsyncTigerGraphConnection

from common.config import (
    graphrag_config,
    embedding_service,
    get_llm_service,
    llm_config,
)
from common.embeddings.base_embedding_store import EmbeddingStore
from common.embeddings.tigergraph_embedding_store import TigerGraphEmbeddingStore
from common.extractors import GraphExtractor, LLMEntityRelationshipExtractor
from common.extractors.BaseExtractor import BaseExtractor
from common.logs.logwriter import LogWriter
from common.db.schema_utils import (
    generate_schema_rep_async,
    get_domain_types_async,
    graphrag_edge_types,
    graphrag_vertex_types,
)

logger = logging.getLogger(__name__)

http_timeout = httpx.Timeout(15.0)

tg_sem = asyncio.Semaphore(graphrag_config.get("tg_concurrency", 10))
load_q = reusable_channel.ReuseableChannel()

# will pause workers until the event is false
loading_event = asyncio.Event()
loading_event.set() # set the event to true to allow the workers to run

# ---------------------------------------------------------------------------
# Auto schema discovery: accumulate entity/relationship types across workers
# ---------------------------------------------------------------------------
_discovered_vertex_types: set[str] = set()
_discovered_edge_triples: set[tuple[str, str, str]] = set()  # (edge_type, from_vtype, to_vtype)
_pending_typed_vertices: list[tuple[str, str, dict]] = []    # (type_name, v_id, attrs)
_pending_typed_edges: list[tuple[str, str, str, str, str, dict | None]] = []
# (src_type, src_id, edge_type, tgt_type, tgt_id, attrs)
_discovery_lock = asyncio.Lock()


def _normalize_type_name(name: str) -> str:
    """Lowercase and strip separators for fuzzy type-name comparison."""
    return name.lower().replace("_", "").replace("-", "").replace(" ", "")


def _find_matching_type(name: str, known_types: list[str]) -> str | None:
    """Return the existing type name whose normalized form equals *name*'s, or None."""
    norm = _normalize_type_name(name)
    for kt in known_types:
        if _normalize_type_name(kt) == norm:
            return kt
    return None


def _sanitize_gsql_name(name: str) -> str:
    """Convert a free-form type name to a valid GSQL identifier."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if s and not s[0].isalpha():
        s = "T_" + s
    return s


async def register_discovered_types(
    entity_types: set[str],
    edge_triples: set[tuple[str, str, str]],
) -> None:
    """Thread-safe registration of types found during extraction."""
    async with _discovery_lock:
        _discovered_vertex_types.update(entity_types)
        _discovered_edge_triples.update(edge_triples)


async def buffer_typed_vertex(type_name: str, v_id: str, attrs: dict) -> None:
    """Buffer a typed vertex for post-schema-creation replay."""
    async with _discovery_lock:
        _pending_typed_vertices.append((type_name, v_id, attrs))


async def buffer_typed_edge(
    src_type: str, src_id: str, edge_type: str,
    tgt_type: str, tgt_id: str, attrs: dict | None,
) -> None:
    """Buffer a typed edge for post-schema-creation replay."""
    async with _discovery_lock:
        _pending_typed_edges.append((src_type, src_id, edge_type, tgt_type, tgt_id, attrs))


def clear_discovered_types() -> None:
    """Reset accumulated types and buffers (call between runs)."""
    _discovered_vertex_types.clear()
    _discovered_edge_triples.clear()
    _pending_typed_vertices.clear()
    _pending_typed_edges.clear()


async def create_discovered_schema_types(
    conn: AsyncTigerGraphConnection,
    existing_vertex_types: list[str],
    existing_edge_types: list[str],
) -> tuple[list[str], list[str]]:
    """Create a schema change job for genuinely new types discovered during
    extraction.

    A discovered type is considered *new* only when its normalised name does
    not match any existing domain or GraphRAG-internal type.  This avoids
    creating near-duplicate types (e.g. "person" vs "Person").

    Returns:
        ``(created_vertex_type_names, created_edge_type_names)``
    """
    async with _discovery_lock:
        pending_vtypes = set(_discovered_vertex_types)
        pending_etriples = set(_discovered_edge_triples)

    if not pending_vtypes and not pending_etriples:
        logger.info("No discovered types to process")
        return [], []

    all_known_vtypes = list(existing_vertex_types) + graphrag_vertex_types
    all_known_etypes = list(existing_edge_types) + graphrag_edge_types

    # --- vertex types -------------------------------------------------------
    vtype_name_map: dict[str, str] = {}   # extracted name -> schema name
    new_vtypes: list[str] = []
    seen_sanitized: set[str] = set()

    for vt in sorted(pending_vtypes):
        match = _find_matching_type(vt, all_known_vtypes)
        if match:
            vtype_name_map[vt] = match
            logger.info(f"Discovered type '{vt}' matches existing '{match}', skipping")
        else:
            safe = _sanitize_gsql_name(vt)
            vtype_name_map[vt] = safe
            if safe not in seen_sanitized:
                new_vtypes.append(safe)
                seen_sanitized.add(safe)

    # --- edge types ---------------------------------------------------------
    edge_groups: dict[str, set[tuple[str, str]]] = defaultdict(set)

    for etype, from_vt, to_vt in pending_etriples:
        if _find_matching_type(etype, all_known_etypes):
            logger.info(f"Discovered edge type '{etype}' matches existing, skipping")
            continue

        safe_etype = _sanitize_gsql_name(etype)

        from_resolved = vtype_name_map.get(from_vt)
        if from_resolved is None:
            from_resolved = _find_matching_type(from_vt, all_known_vtypes) or "Entity"
        to_resolved = vtype_name_map.get(to_vt)
        if to_resolved is None:
            to_resolved = _find_matching_type(to_vt, all_known_vtypes) or "Entity"

        all_valid = set(all_known_vtypes) | seen_sanitized
        if from_resolved not in all_valid:
            from_resolved = "Entity"
        if to_resolved not in all_valid:
            to_resolved = "Entity"

        edge_groups[safe_etype].add((from_resolved, to_resolved))

    if not new_vtypes and not edge_groups:
        logger.info("All discovered types match existing schema, no changes needed")
        return [], []

    # --- build GSQL ---------------------------------------------------------
    stmts: list[str] = []
    for vt in new_vtypes:
        stmts.append(
            f"ADD VERTEX {vt} ("
            f"PRIMARY_ID id STRING, "
            f"description LIST<STRING>, "
            f"epoch_added INT"
            f') WITH primary_id_as_attribute="true"'
        )

    for etype, pairs in sorted(edge_groups.items()):
        pair_strs = [f"FROM {f}, TO {t}" for f, t in sorted(pairs)]
        stmts.append(
            f"ADD DIRECTED EDGE {etype} ("
            + " | ".join(pair_strs)
            + ", relation_type STRING)"
        )

    # Allow CONTAINS_ENTITY to connect DocumentChunk to each new vertex type
    for vt in new_vtypes:
        stmts.append(
            f"ALTER EDGE CONTAINS_ENTITY ADD PAIR (FROM DocumentChunk, TO {vt})"
        )

    job_name = f"auto_schema_{int(time.time())}"
    gsql = f"USE GRAPH {conn.graphname}\n"
    gsql += f"CREATE SCHEMA_CHANGE JOB {job_name} FOR GRAPH {conn.graphname} {{\n"
    for s in stmts:
        gsql += f"  {s};\n"
    gsql += "}\n"
    gsql += f"RUN SCHEMA_CHANGE JOB {job_name}\n"
    gsql += f"DROP JOB {job_name}\n"

    logger.info(f"Auto schema creation GSQL:\n{gsql}")

    try:
        async with tg_sem:
            result = await conn.gsql(gsql)
        if isinstance(result, str) and "error" in result.lower():
            logger.error(f"Auto schema creation failed: {result}")
            return [], []
    except Exception as e:
        logger.error(f"Auto schema creation exception: {e}")
        return [], []

    created_etypes = list(edge_groups.keys())
    logger.info(
        f"Auto schema creation complete: "
        f"{len(new_vtypes)} vertex type(s), {len(created_etypes)} edge type(s)"
    )
    return new_vtypes, created_etypes


async def replay_typed_data(
    conn: AsyncTigerGraphConnection,
    new_vtypes: list[str],
    new_etypes: list[str],
    batch_size: int = 500,
) -> None:
    """Replay buffered typed vertices and edges after schema creation.

    Reads from ``_pending_typed_vertices`` and ``_pending_typed_edges``,
    batches them into upsert payloads, and writes directly to TigerGraph
    via ``upsert_batch()``.
    """
    async with _discovery_lock:
        vertices = list(_pending_typed_vertices)
        edges = list(_pending_typed_edges)

    if not vertices and not edges:
        logger.info("No buffered typed data to replay")
        return

    new_vtypes_set = set(new_vtypes)
    new_etypes_set = set(new_etypes)

    # --- replay vertices ----------------------------------------------------
    batch: dict = {"vertices": defaultdict(dict)}
    count = 0
    for type_name, v_id, attrs in vertices:
        safe = _sanitize_gsql_name(type_name)
        if safe not in new_vtypes_set:
            continue
        batch["vertices"][safe][v_id] = map_attrs(attrs)
        count += 1
        if count >= batch_size:
            await upsert_batch(conn, json.dumps(batch))
            batch = {"vertices": defaultdict(dict)}
            count = 0
    if count > 0:
        await upsert_batch(conn, json.dumps(batch))
    logger.info(f"Replayed {len(vertices)} typed vertex upserts")

    # --- replay edges -------------------------------------------------------
    dd = lambda: defaultdict(dd)  # infinite default dict
    edge_batch: dict = {"edges": dd()}
    count = 0
    for src_type, src_id, edge_type, tgt_type, tgt_id, attrs in edges:
        safe_etype = _sanitize_gsql_name(edge_type)
        safe_src = _sanitize_gsql_name(src_type) if src_type != "DocumentChunk" else src_type
        safe_tgt = _sanitize_gsql_name(tgt_type)

        # Only replay edges whose types were actually created (or CONTAINS_ENTITY)
        is_contains = edge_type == "CONTAINS_ENTITY"
        is_new_edge = safe_etype in new_etypes_set
        if not is_contains and not is_new_edge:
            continue
        # For CONTAINS_ENTITY, target must be a new type
        if is_contains and safe_tgt not in new_vtypes_set:
            continue

        edge_label = "CONTAINS_ENTITY" if is_contains else safe_etype
        formatted_attrs = map_attrs(attrs) if attrs else {}
        edge_batch["edges"][safe_src][src_id][edge_label][safe_tgt][tgt_id] = formatted_attrs
        count += 1
        if count >= batch_size:
            await upsert_batch(conn, json.dumps(edge_batch))
            edge_batch = {"edges": dd()}
            count = 0
    if count > 0:
        await upsert_batch(conn, json.dumps(edge_batch))
    logger.info(f"Replayed {len(edges)} typed edge upserts")


async def install_queries(
    requried_queries: list[str],
    conn: AsyncTigerGraphConnection,
):
    # queries that are currently installed
    installed_queries = [q.split("/")[-1] for q in await conn.getEndpoints(dynamic=True) if f"/{conn.graphname}/" in q]

    # doesn't need to be parallel since tg only does it one at a time
    for q in requried_queries:
        # only install n queries at a time (n=n_workers)
        q_name = q.split("/")[-1]
        # if the query is not installed, install it
        if q_name not in installed_queries:
            res = await workers.install_query(conn, q, False)
            # stop system if a required query doesn't install
            if res["error"]:
                raise Exception(res["message"])
            logger.info(f"Successfully created query '{q_name}'.")
    query = f"""\
USE GRAPH {conn.graphname}
INSTALL QUERY ALL
"""
    async with tg_sem:
        res = await conn.gsql(query)
        if "error" in res:
            raise Exception(res)

    logger.info("Finished processing all required queries.")


async def init(
    conn: AsyncTigerGraphConnection,
) -> tuple[BaseExtractor, dict[str, EmbeddingStore], list[str]]:
    """Initialize extractors, embedding store, and return domain vertex types.

    Returns:
        (extractor, embedding_store, domain_vertex_types)
    """
    # install requried queries
    requried_queries = [
        "common/gsql/graphrag/StreamIds",
        "common/gsql/graphrag/StreamDocContent",
        "common/gsql/graphrag/StreamChunkContent",
        "common/gsql/graphrag/SetEpochProcessing",
        "common/gsql/graphrag/ResolveRelationships",
        "common/gsql/graphrag/get_community_children",
        "common/gsql/graphrag/entities_have_resolution",
        "common/gsql/graphrag/communities_have_desc",
        "common/gsql/graphrag/get_vertices_or_remove",
        "common/gsql/graphrag/louvain/graphrag_louvain_init",
        "common/gsql/graphrag/louvain/graphrag_louvain_communities",
        "common/gsql/graphrag/louvain/modularity",
        "common/gsql/graphrag/louvain/stream_community",
        "common/gsql/supportai/create_entity_type_relationships"
    ]
    # add louvain to queries
    q = [x.split(".gsql")[0] for x in glob("common/gsql/graphrag/louvain/*")]
    requried_queries.extend(q)
    logger.info(f"Installing queries needed for GraphRAG all together")
    await install_queries(requried_queries, conn)

    # Retrieve domain vertex/edge types (user schema, excluding GraphRAG internals)
    domain_vertex_types, domain_edge_types = await get_domain_types_async(conn)
    logger.info(f"Domain vertex types: {domain_vertex_types}")
    logger.info(f"Domain edge types: {domain_edge_types}")

    strict_schema = graphrag_config.get("strict_schema_mode", False)

    # extractor
    if graphrag_config.get("extractor") == "graphrag":
        extractor = GraphExtractor()
    elif graphrag_config.get("extractor") == "llm":
        kwargs = {}
        if graphrag_config.get("use_graph_schema", True):
            kwargs["graph_schema"] = await generate_schema_rep_async(conn, graphrag=True)
            if domain_vertex_types:
                kwargs["allowed_entity_types"] = domain_vertex_types
            if domain_edge_types:
                kwargs["allowed_relationship_types"] = domain_edge_types
        kwargs["strict_mode"] = strict_schema
        extractor = LLMEntityRelationshipExtractor(get_llm_service(llm_config), **kwargs)
    else:
        raise ValueError("Invalid extractor type")

    embedding_store = TigerGraphEmbeddingStore(
        conn,
        embedding_service,
        support_ai_instance=True,
    )
    embedding_store.set_graphname(conn.graphname)

    return extractor, embedding_store, domain_vertex_types


def make_headers(conn: AsyncTigerGraphConnection):
    if conn.apiToken is None or conn.apiToken == "":
        tkn = base64.b64encode(f"{conn.username}:{conn.password}".encode()).decode()
        headers = {"Authorization": f"Basic {tkn}"}
    else:
        headers = {"Authorization": f"Bearer {conn.apiToken}"}

    return headers


async def stream_ids(
    conn: AsyncTigerGraphConnection, v_type: str, current_batch: int, ttl_batches: int
) -> dict[str, str | list[str]]:
    try:
        async with tg_sem:
            res = await conn.runInstalledQuery(
                "StreamIds",
                params={
                    "current_batch": current_batch,
                    "ttl_batches": ttl_batches,
                    "v_type": v_type,
                }
            )
        ids = res[0]["@@ids"]
        logger.debug(f"Fetched ids: {ids}")
        return {"error": False, "ids": ids}

    except Exception as e:
        exc = traceback.format_exc()
        LogWriter.error(f"/{conn.graphname}/query/StreamIds\nException Trace:\n{exc}")

        return {"error": True, "message": str(e)}


def map_attrs(attributes: dict):
    # map attrs
    attrs = {}
    for k, v in attributes.items():
        if isinstance(v, tuple):
            attrs[k] = {"value": v[0], "op": v[1]}
        elif isinstance(v, dict):
            attrs[k] = {
                "value": {"keylist": list(v.keys()), "valuelist": list(v.values())}
            }
        else:
            attrs[k] = {"value": v}
    return attrs


def process_id(v_id: str):
    has_func = re.compile(r"(.*)\(").findall(v_id)
    if len(has_func) > 0:
        v_id = has_func[0]
    v_id = v_id.replace(" ", "-").lower().replace("/", "_").replace("(", "").replace(")", "")
    if v_id == "''" or v_id == '""':
        return ""

    return v_id


async def upsert_vertex(
    conn: AsyncTigerGraphConnection,
    vertex_type: str,
    vertex_id: str,
    attributes: dict,
):
    logger.debug(f"Upsert vertex: {vertex_id} as {vertex_type}")
    vertex_id = vertex_id.replace(" ", "_")
    attrs = map_attrs(attributes)
    await load_q.put(("vertices", (vertex_type, vertex_id, attrs)))


async def upsert_batch(conn: AsyncTigerGraphConnection, data: str):
    async with tg_sem:
        try:
            res = await conn.upsertData(data)
            logger.info(f"Upsert res: {res}")
        except Exception as e:
            err = traceback.format_exc()
            logger.error(f"Upsert err with {data}:\n{err}")
            return {"error": True, "message": str(e)}


async def check_vertex_exists(conn, v_id: str):
    async with tg_sem:
        try:
            res = await conn.getVerticesById("Entity", v_id)

        except Exception as e:
            if "is not a valid vertex id" not in str(e):
                err = traceback.format_exc()
                logger.error(f"Check err:\n{err}")
            return {"error": True, "message": str(e)}

        return {"error": False, "resp": res}


async def batch_check_vertices(
    conn: AsyncTigerGraphConnection,
    ids: list[str],
    domain_vertex_types: list[str],
) -> dict[str, str]:
    """Check which IDs already exist as vertices in any domain vertex type.

    Returns a mapping of ``{vertex_id: vertex_type}`` for IDs that were found.
    IDs not found in any domain type are omitted from the result.
    """
    found: dict[str, str] = {}
    if not ids or not domain_vertex_types:
        return found

    for v_type in domain_vertex_types:
        remaining = [vid for vid in ids if vid not in found]
        if not remaining:
            break
        try:
            async with tg_sem:
                res = await conn.getVerticesById(v_type, remaining)
            for v in res:
                found[v["v_id"]] = v_type
        except Exception:
            pass
    return found


async def upsert_edge(
    conn: AsyncTigerGraphConnection,
    src_v_type: str,
    src_v_id: str,
    edge_type: str,
    tgt_v_type: str,
    tgt_v_id: str,
    attributes: dict = None,
):
    if attributes is None:
        attrs = {}
    else:
        attrs = map_attrs(attributes)
    logger.debug(f"Upsert edge: {src_v_id} -[{edge_type}]-> {tgt_v_id}")
    src_v_id = src_v_id.replace(" ", "_")
    tgt_v_id = tgt_v_id.replace(" ", "_")
    await load_q.put(
        (
            "edges",
            (
                src_v_type,
                src_v_id,
                edge_type,
                tgt_v_type,
                tgt_v_id,
                attrs,
            ),
        )
    )


async def get_commuinty_children(conn, i: int, c: str):
    async with tg_sem:
        try:
            resp = await conn.runInstalledQuery(
                "get_community_children",
                params={"comm": c, "iter": i}
            )
        except:
            logger.error(f"Get Children err:\n{traceback.format_exc()}")

    descrs = []
    try:
        res = resp[0]["children"]
    except Exception as e:
        logger.error(f"Get Children err:\n{e}")
        res = []
    for d in res:
        desc = d["attributes"]["description"]
        # if it's the entity iteration
        if i == 1:
            # filter out empty strings
            desc = list(filter(lambda x: len(x) > 0, desc))
            # if there are no descriptions, make it the v_id
            if len(desc) == 0:
                desc.append(d["v_id"])
            descrs.extend(desc)
        else:
            descrs.append(desc)

    return descrs


async def check_all_ents_resolved(conn):
    try:
        async with tg_sem:
            resp = await conn.runInstalledQuery(
                "entities_have_resolution"
            )
    except Exception as e:
        logger.error(f"Check Vert Desc err:\n{e}")

    res = resp[0]["all_resolved"]
    logger.info(resp)

    return res

async def add_rels_between_types(conn):
    try:
        async with tg_sem:
            resp = await conn.runInstalledQuery(
                "create_entity_type_relationships"
            )
    except Exception as e:
        logger.error(f"Check Vert EntityType err:\n{e}")
        return {"error": True, "message": e}        
    return resp[0]

async def check_vertex_has_desc(conn, i: int):
    try:
        async with tg_sem:
            resp = await conn.runInstalledQuery(
                "communities_have_desc",
                params={"iter": i},
            )
    except Exception as e:
        logger.error(f"Check Vert Desc err:\n{e}")

    res = resp[0]["all_have_desc"]
    logger.info(res)

    return res

async def check_embedding_rebuilt(conn, v_type: str):
    try:
        async with tg_sem:
            resp = await conn.runInstalledQuery(
                "vertices_have_embedding",
                params={
                    "vertex_type": v_type,
                }
            )
    except Exception as e:
        logger.error(f"Check embedding rebuilt err:\n{e}")

    res = resp[0]["all_have_embedding"]
    logger.info(resp)

    return res
