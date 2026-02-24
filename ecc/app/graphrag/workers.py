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
import logging
import time
import json
import traceback
from urllib.parse import quote_plus
from typing import Iterable, List, Optional, Tuple

import ecc_util
import httpx
from aiochannel import Channel
from graphrag import community_summarizer, util
from langchain_community.graphs.graph_document import GraphDocument, Node
from pyTigerGraph import AsyncTigerGraphConnection

from common.config import graphrag_config
from common.db.schema_utils import graphrag_vertex_types, graphrag_edge_types
from common.embeddings.embedding_services import EmbeddingModel
from common.embeddings.base_embedding_store import EmbeddingStore
from common.extractors import BaseExtractor, LLMEntityRelationshipExtractor
from common.logs.logwriter import LogWriter

logger = logging.getLogger(__name__)

async def install_query(
    conn: AsyncTigerGraphConnection, query_path: str, install: bool = True
) -> dict[str, httpx.Response | str | None]:
    LogWriter.info(f"Installing query {query_path}")
    with open(f"{query_path}.gsql", "r") as f:
        query = f.read()

    query_name = query_path.split("/")[-1]
    query = f"""\
USE GRAPH {conn.graphname}
{query}
"""
    if install:
       query += f"""
INSTALL QUERY {query_name}
"""
    async with util.tg_sem:
        res = await conn.gsql(query)

    if "error" in res:
        LogWriter.error(res)
        return {
            "result": None,
            "error": True,
            "message": f"Failed to install query {query_name}",
        }

    return {"result": res, "error": False}


chunk_sem = asyncio.Semaphore(20)


async def chunk_doc(
    conn: AsyncTigerGraphConnection,
    doc: dict[str, str],
    upsert_chan: Channel,
    embed_chan: Channel,
    extract_chan: Channel,
):
    """
    Chunks a document.
    Places the resulting chunks into the upsert channel (to be upserted to TG)
    and the embed channel (to be embedded and written to the vector store)
    """

    # if loader is running, wait until it's done
    if not util.loading_event.is_set():
        logger.info("Chunk worker waiting for loading event to finish")
        await util.loading_event.wait()

    async with chunk_sem:
        if "ctype" in doc["attributes"]:
            chunker_type = doc["attributes"]["ctype"].lower().strip()
        else:
            chunker_type = ""
        
        v_id = util.process_id(doc["v_id"])
        if v_id != doc["v_id"]:
            logger.info(f"""Cloning doc/content {doc["v_id"]} -> {v_id}""")
            await upsert_chan.put((upsert_doc, (conn, v_id, chunker_type, doc["attributes"]["text"])))
        
        # Use get_chunker for all types (including images)
        # For images, get_chunker returns SingleChunker which preserves markdown image references
        chunker = ecc_util.get_chunker(chunker_type)
        # decode the text return from tigergraph as it was encoded when written into jsonl file for uploading
        chunks = chunker.chunk(doc["attributes"]["text"].encode('utf-8').decode('unicode_escape'))
       
        logger.info(f"Chunking {v_id} into {len(chunks)} chunk(s)")
        for i, chunk in enumerate(chunks):
            chunk_id = f"{v_id}_chunk_{i}"
            logger.info(f"Processing chunk {chunk_id}")

            # send chunks to be upserted (func, args)
            logger.info("chunk writes to upsert_chan")
            await upsert_chan.put((upsert_chunk, (conn, v_id, chunk_id, chunk)))

            # send chunks to have entities extracted
            logger.info("chunk writes to extract_chan")
            await extract_chan.put((chunk, chunk_id))

            # send chunks to be embedded
            logger.info("chunk writes to embed_chan")
            await embed_chan.put((chunk_id, chunk, "DocumentChunk"))

    return v_id


async def upsert_doc(conn: AsyncTigerGraphConnection, doc_id, ctype, content_text):
    date_added = int(time.time())
    await util.upsert_vertex(
        conn,
        "Document",
        doc_id,
        attributes={"epoch_added": date_added, "epoch_processed": date_added},
    )
    await util.upsert_vertex(
        conn,
        "Content",
        doc_id,
        attributes={"ctype": ctype, "text": content_text, "epoch_added": date_added},
    )
    await util.upsert_edge(
        conn, "Document", doc_id, "HAS_CONTENT", "Content", doc_id
    )

async def upsert_chunk(conn: AsyncTigerGraphConnection, doc_id, chunk_id, chunk):
    logger.info(f"Upserting chunk {chunk_id}")
    date_added = int(time.time())
    await util.upsert_vertex(
        conn,
        "DocumentChunk",
        chunk_id,
        attributes={"epoch_added": date_added, "epoch_processed": date_added, "idx": int(chunk_id.split("_")[-1])},
    )
    await util.upsert_vertex(
        conn,
        "Content",
        chunk_id,
        attributes={"text": chunk, "epoch_added": date_added},
    )
    await util.upsert_edge(
        conn, "DocumentChunk", chunk_id, "HAS_CONTENT", "Content", chunk_id
    )
    await util.upsert_edge(
        conn, "Document", doc_id, "HAS_CHILD", "DocumentChunk", chunk_id
    )
    if int(chunk_id.split("_")[-1]) > 0:
        await util.upsert_edge(
            conn,
            "DocumentChunk",
            chunk_id,
            "IS_AFTER",
            "DocumentChunk",
            doc_id + "_chunk_" + str(int(chunk_id.split("_")[-1]) - 1),
        )


embed_sem = asyncio.Semaphore(20)


async def embed(
    embed_svc: EmbeddingModel,
    embed_store: EmbeddingStore,
    v_id: str | Tuple[str, str],
    content: str,
):
    """
    Args:
        graphname: str
            the name of the graph the documents are in
        embed_svc: EmbeddingModel
            The class used to vectorize text
        embed_store:
            The class used to store the vectore to a vector DB
        v_id: str
            the vertex id that will be embedded
        content: str
            the content of the document/chunk
        index_name: str
            the vertex index to write to
    """
    async with embed_sem:
        logger.info(f"Embedding {v_id}")

        # if loader is running, wait until it's done
        if not util.loading_event.is_set():
            logger.info("Embed worker waiting for loading event to finish")
            await util.loading_event.wait()
        try:
            await embed_store.aadd_embeddings([(content, [])], [{"vertex_id": v_id}])
        except Exception as e:
            logger.error(f"Failed to add embeddings for {v_id}: {e}")


async def get_vert_desc(conn, v_id, node: Node):
    desc = [node.properties.get("description", "")]
    exists = await util.check_vertex_exists(conn, v_id)
    # if vertex exists, get description content and append this description to it
    if not exists.get("error", False):
        # deduplicate descriptions
        desc.extend(exists["resp"][0]["attributes"]["description"])
        desc = list(set(desc))
    return desc


extract_sem = asyncio.Semaphore(20)


async def extract(
    upsert_chan: Channel,
    embed_chan: Channel,
    extractor: BaseExtractor,
    conn: AsyncTigerGraphConnection,
    chunk: str,
    chunk_id: str,
    vertex_types: List[str],
    domain_vertex_types: Optional[List[str]] = None,
):
    # if loader is running, wait until it's done
    if not util.loading_event.is_set():
        logger.info("Extract worker waiting for loading event to finish")
        await util.loading_event.wait()

    embed_entities = graphrag_config.get("embed_entities", True)
    entity_match_mode = graphrag_config.get("entity_match_mode", "merge")
    auto_schema = graphrag_config.get("auto_schema_creation", False)

    async with extract_sem:
        try:
            extracted: list[GraphDocument] = await extractor.aextract(chunk)
            logger.info(
                f"Extracting chunk: {chunk_id} ({len(extracted)} graph docs extracted)"
            )
        except Exception as e:
            logger.error(f"Failed to extract chunk {chunk_id}: {e}")
            extracted = []

        # -- Auto schema discovery: collect entity/relationship types ------
        if graphrag_config.get("auto_schema_creation", False) and extracted:
            _entity_types: set[str] = set()
            _edge_triples: set[tuple[str, str, str]] = set()
            for doc in extracted:
                for node in doc.nodes:
                    ntype = getattr(node, "type", None)
                    if ntype and ntype != "Node":
                        _entity_types.add(ntype)
                for edge in doc.relationships:
                    etype = getattr(edge, "type", None)
                    if etype:
                        src_type = getattr(edge.source, "type", None) or "Entity"
                        tgt_type = getattr(edge.target, "type", None) or "Entity"
                        if src_type == "Node":
                            src_type = "Entity"
                        if tgt_type == "Node":
                            tgt_type = "Entity"
                        _edge_triples.add((etype, src_type, tgt_type))
            if _entity_types or _edge_triples:
                await util.register_discovered_types(_entity_types, _edge_triples)

        # -- Batch check: collect all entity IDs from this chunk's extraction,
        #    then check which ones already exist as domain vertices. ---------
        all_entity_ids: list[str] = []
        for doc in extracted:
            for node in doc.nodes:
                v_id = util.process_id(str(node.id))
                if v_id:
                    all_entity_ids.append(v_id)
            for edge in doc.relationships:
                for endpoint in (edge.source, edge.target):
                    v_id = util.process_id(endpoint.id)
                    if v_id:
                        all_entity_ids.append(v_id)
        all_entity_ids = list(set(all_entity_ids))

        existing_map: dict[str, str] = {}
        if entity_match_mode != "create_always" and domain_vertex_types:
            existing_map = await util.batch_check_vertices(
                conn, all_entity_ids, domain_vertex_types
            )
            if existing_map:
                logger.info(f"Found {len(existing_map)} existing domain vertices for chunk {chunk_id}")

        seen_embedded: set[str] = set()

        async def _maybe_embed_entity(v_id: str, content: str):
            """Push to embed channel if embed_entities is on and not yet seen."""
            if not embed_entities:
                return
            if v_id in seen_embedded:
                return
            seen_embedded.add(v_id)
            await embed_chan.put((v_id, content, "Entity"))

        def _entity_is_existing(v_id: str) -> Optional[str]:
            """Return the domain vertex type if v_id matches an existing vertex, else None."""
            return existing_map.get(v_id)

        # upsert nodes and edges to the graph
        for doc in extracted:
            for i, node in enumerate(doc.nodes):
                logger.info(f"extract writes entity vert to upsert\nNode: {node.id}")
                v_id = util.process_id(str(node.id))
                type_id = util.process_id(node.type)
                if len(v_id) == 0:
                    continue

                matched_type = _entity_is_existing(v_id)

                if matched_type:
                    # Entity already exists as a domain vertex -- link chunk to it
                    logger.info(f"Linking chunk {chunk_id} to existing {matched_type} vertex {v_id}")
                    await upsert_chan.put((
                        util.upsert_edge,
                        (conn, "DocumentChunk", chunk_id, "CONTAINS_ENTITY",
                         matched_type, v_id, None),
                    ))
                    continue

                if entity_match_mode == "link_only":
                    logger.info(f"Skipping entity {v_id} (link_only mode, not found in domain)")
                    continue

                # "merge" or "create_always": create the Entity vertex
                desc = await get_vert_desc(conn, v_id, node)
                if len(desc[0]) == 0:
                    desc[0] = str(node.id)

                entity_attrs = {
                    "description": desc,
                    "entity_type": type_id,
                    "epoch_added": int(time.time()),
                }
                await upsert_chan.put((
                    util.upsert_vertex,
                    (conn, "Entity", v_id, entity_attrs),
                ))

                # Buffer typed vertex for post-schema-creation replay
                if auto_schema and node.type and node.type != "Node":
                    await util.buffer_typed_vertex(node.type, v_id, {
                        "description": desc,
                        "epoch_added": entity_attrs["epoch_added"],
                    })
                    await util.buffer_typed_edge(
                        "DocumentChunk", chunk_id, "CONTAINS_ENTITY",
                        node.type, v_id, None,
                    )

                await _maybe_embed_entity(v_id, desc[0])

                # upsert type vert
                if isinstance(extractor, LLMEntityRelationshipExtractor):
                    logger.info("extract writes type vert to upsert")
                    if len(type_id) == 0:
                        continue
                    await upsert_chan.put((
                        util.upsert_vertex,
                        (conn, "EntityType", type_id, {
                            "epoch_added": int(time.time()),
                        }),
                    ))
                    logger.info("extract writes entity_has_type edge to upsert")
                    await upsert_chan.put((
                        util.upsert_edge,
                        (conn, "Entity", v_id, "ENTITY_HAS_TYPE",
                         "EntityType", type_id, None),
                    ))

                # Link the vertex to the chunk via the domain type if applicable
                if type_id in vertex_types and type_id not in graphrag_vertex_types:
                    logger.info(f"extract writes contains edge of {v_id} of type {type_id} to upsert")
                    await upsert_chan.put((
                        util.upsert_edge,
                        (conn, "DocumentChunk", chunk_id, "CONTAINS_ENTITY",
                         type_id, v_id, None),
                    ))

                # link the entity to the chunk it came from
                logger.info("extract writes contains edge to upsert")
                await upsert_chan.put((
                    util.upsert_edge,
                    (conn, "DocumentChunk", chunk_id, "CONTAINS_ENTITY",
                     "Entity", v_id, None),
                ))

                for node2 in doc.nodes[i + 1:]:
                    v_id2 = util.process_id(str(node2.id))
                    if len(v_id2) == 0:
                        continue
                    await upsert_chan.put((
                        util.upsert_edge,
                        (conn, "Entity", v_id, "RELATIONSHIP",
                         "Entity", v_id2,
                         {"relation_type": "DOC_CHUNK_COOCCURRENCE"}),
                    ))

            for edge in doc.relationships:
                logger.info(
                    f"extract writes relates edge to upsert:{edge.source.id} -({edge.type})->  {edge.target.id}"
                )
                src_id = util.process_id(edge.source.id)
                tgt_id = util.process_id(edge.target.id)
                if not src_id or not tgt_id:
                    continue

                src_matched = _entity_is_existing(src_id)
                tgt_matched = _entity_is_existing(tgt_id)

                src_type = src_matched or "Entity"
                tgt_type = tgt_matched or "Entity"

                # upsert source vertex (only if not an existing domain vertex)
                if not src_matched:
                    if entity_match_mode == "link_only":
                        continue
                    desc = await get_vert_desc(conn, src_id, edge.source)
                    if len(desc[0]) == 0:
                        desc[0] = str(edge.source.id)
                    await _maybe_embed_entity(src_id, desc[0])
                    src_attrs = {
                        "description": desc,
                        "epoch_added": int(time.time()),
                    }
                    await upsert_chan.put((
                        util.upsert_vertex,
                        (conn, "Entity", src_id, src_attrs),
                    ))
                    src_node_type = getattr(edge.source, "type", None)
                    if auto_schema and src_node_type and src_node_type != "Node":
                        await util.buffer_typed_vertex(src_node_type, src_id, src_attrs)

                # upsert target vertex (only if not an existing domain vertex)
                if not tgt_matched:
                    if entity_match_mode == "link_only":
                        continue
                    desc = await get_vert_desc(conn, tgt_id, edge.target)
                    if len(desc[0]) == 0:
                        desc[0] = str(edge.target.id)
                    await _maybe_embed_entity(tgt_id, desc[0])
                    tgt_attrs = {
                        "description": desc,
                        "epoch_added": int(time.time()),
                    }
                    await upsert_chan.put((
                        util.upsert_vertex,
                        (conn, "Entity", tgt_id, tgt_attrs),
                    ))
                    tgt_node_type = getattr(edge.target, "type", None)
                    if auto_schema and tgt_node_type and tgt_node_type != "Node":
                        await util.buffer_typed_vertex(tgt_node_type, tgt_id, tgt_attrs)

                # upsert the edge between the two entities (using actual types)
                await upsert_chan.put((
                    util.upsert_edge,
                    (conn, src_type, src_id, "RELATIONSHIP",
                     tgt_type, tgt_id, {"relation_type": edge.type}),
                ))

                # Buffer typed edge for post-schema-creation replay
                if auto_schema and edge.type:
                    src_node_type = getattr(edge.source, "type", None) or "Entity"
                    tgt_node_type = getattr(edge.target, "type", None) or "Entity"
                    if src_node_type == "Node":
                        src_node_type = "Entity"
                    if tgt_node_type == "Node":
                        tgt_node_type = "Entity"
                    await util.buffer_typed_edge(
                        src_node_type, src_id, edge.type,
                        tgt_node_type, tgt_id, {"relation_type": edge.type},
                    )


resolve_sem = asyncio.Semaphore(20)


async def resolve_entity(
    conn: AsyncTigerGraphConnection,
    upsert_chan: Channel,
    embed_store: EmbeddingStore,
    entity_id: str | Tuple[str, str],
):
    """
    get all vectors of E (one name can have multiple discriptions)
    get ents close to E
    for e in ents:
        if e is 95% similar to E and edit_dist(E,e) <=3:
            merge
            mark e as processed

    mark as processed
    """

    # if loader is running, wait until it's done
    if not util.loading_event.is_set():
        logger.info("Entity Resolution worker waiting for loading event to finish")
        await util.loading_event.wait()

    async with resolve_sem:
        try:
            logger.info(f"Resolving Entity {entity_id}")
            results = await embed_store.aget_k_closest(entity_id)
            logger.info(f"Resolving Entity {entity_id} to {results}")

        except Exception:
            err = traceback.format_exc()
            logger.error(err)
            return

        if len(results) == 0:
            logger.error(
                f"aget_k_closest should, minimally, return the entity itself.\n{results}"
            )
            raise Exception()

        # merge all entities into the ResolvedEntity vertex
        # use the longest v_id as the resolved entity's v_id
        if isinstance(entity_id, tuple):
          resolved_entity_id = entity_id[0]
        else:
          resolved_entity_id = entity_id
        for v in results:
            if len(v) > len(resolved_entity_id):
                resolved_entity_id = v

        logger.debug(f"Merging {results} to ResolvedEntity {resolved_entity_id}")
        # upsert the resolved entity
        await upsert_chan.put(
            (
                util.upsert_vertex,  # func to call
                (
                    conn,
                    "ResolvedEntity",  # v_type
                    resolved_entity_id,  # v_id
                    {  # attrs
                    },
                ),
            )
        )

        # create RESOLVES_TO edges from each entity to the ResolvedEntity
        for v in results:
            await upsert_chan.put(
                (
                    util.upsert_edge,
                    (
                        conn,
                        "Entity",  # src_type
                        v,  # src_id
                        "RESOLVES_TO",  # edge_type
                        "ResolvedEntity",  # tgt_type
                        resolved_entity_id,  # tgt_id
                        None,  # attributes
                    ),
                )
            )


comm_sem = asyncio.Semaphore(20)


async def process_community(
    conn: AsyncTigerGraphConnection,
    upsert_chan: Channel,
    embed_chan: Channel,
    i: int,
    comm_id: str,
):
    """
    https://github.com/microsoft/graphrag/blob/main/graphrag/prompt_tune/template/community_report_summarization.py

    Get children verts (Entity for layer-1 Communities, Community otherwise)
    if the commuinty only has one child, use its description -- no need to summarize

    embed summaries
    """
    # if loader is running, wait until it's done
    if not util.loading_event.is_set():
        logger.info("Process Community worker waiting for loading event to finish")
        await util.loading_event.wait()

    async with comm_sem:
        logger.info(f"Processing Community: {comm_id}")
        # get the children of the community
        children = await util.get_commuinty_children(conn, i, comm_id)
        err = False

        # if the community only has one child, use its description
        if len(children) == 1:
            summary = children[0]
        else:
            llm = ecc_util.get_llm_service()
            summarizer = community_summarizer.CommunitySummarizer(llm)
            summary = await summarizer.summarize(comm_id, children)
            if summary["error"]:
                summary = await summarizer.summarize(comm_id, children)
                if summary["error"]:
                    logger.error(f"Failed to summarize community {comm_id} with message {summary['message']}")
                summary = "Should ignore due to summary error."
            else:
                summary = summary["summary"]

        if not err:
            logger.debug(f"Community {comm_id}: {children}, {summary}")
            await upsert_chan.put(
                (
                    util.upsert_vertex,  # func to call
                    (
                        conn,
                        "Community",  # v_type
                        comm_id,  # v_id
                        {  # attrs
                            "description": summary,
                            "iteration": i,
                        },
                    ),
                )
            )

            # (v_id, content, index_name)
            await embed_chan.put((comm_id, summary, "Community"))
