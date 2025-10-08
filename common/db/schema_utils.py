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

import logging
from typing import List
from pyTigerGraph import AsyncTigerGraphConnection, TigerGraphConnection
from common.metrics.tg_proxy import TigerGraphConnectionProxy

logger = logging.getLogger(__name__)

# Internal cache for schema representations
_schema_cache = {}

graphrag_vertex_types = ["DocumentCollection", "Document","DocumentChunk", "Entity", "EntityType", "Relationship", "ResolvedEntity", "Content", "Concept", "Community"]
graphrag_edge_types = ["CONTAINS_ENTITY", "CONTAINS_CHUNK", "RELATIONSHIP", "RELATES", "HAS_TYPE", "HAS_HEAD", "HAS_TAIL", "HAS_CONTENT", "HAS_CONCEPT", "HAS_COMMUNITY"]

def get_schema_ver(conn: TigerGraphConnectionProxy) -> int:
    """Retrieves the schema version of the graph by running an interpreted query.

    Returns:
        The schema version as an integer.
    """
    logger.info("entry: _get_schema_ver")

    # Create the interpreted query to get schema version
    query_text = f'INTERPRET QUERY () FOR GRAPH {conn.graphname} {{ PRINT "OK"; }}'

    try:
        # Run the interpreted query
        #result = self.conn.runInterpretedQuery(query_text)
        if conn._version_greater_than_4_0():
            ret = conn._post(conn.gsUrl + "/gsql/v1/queries/interpret",
                            params={}, data=query_text, authMode="pwd", resKey="version",
                            headers={'Content-Type': 'text/plain'})
        else:
            ret = conn._post(conn.gsUrl + "/gsqlserver/interpreted_query", data=query_text,
                            params={}, authMode="pwd", resKey="version")

        schema_version_int = None
        if isinstance(ret, dict) and "schema" in ret:
            schema_version = ret["schema"]
            try:
                schema_version_int = int(schema_version)
            except (ValueError, TypeError):
                logger.warning(f"Schema version '{schema_version}' could not be converted to integer")
        if schema_version_int is None:
            logger.warning("Schema version not found in query result")
        logger.info("exit: _get_schema_ver")
        return schema_version_int

    except Exception as e:
        logger.error(f"Error getting schema version: {str(e)}")
        raise Exception(f"Failed to get schema version: {str(e)}")

async def get_schema_ver_async(conn: AsyncTigerGraphConnection) -> int:
    """Retrieves the schema version of the graph by running an interpreted query for async connections.

    Returns:
        The schema version as an integer.
    """
    logger.info("entry: _get_schema_ver_async")

    # Create the interpreted query to get schema version
    query_text = f'INTERPRET QUERY () FOR GRAPH {conn.graphname} {{ PRINT "OK"; }}'

    try:
        # Run the interpreted query using async methods
        if await conn._version_greater_than_4_0():
            ret = await conn._post(conn.gsUrl + "/gsql/v1/queries/interpret",
                                 params={}, data=query_text, authMode="pwd", resKey="version",
                                 headers={'Content-Type': 'text/plain'})
        else:
            ret = await conn._post(conn.gsUrl + "/gsqlserver/interpreted_query", data=query_text,
                                 params={}, authMode="pwd", resKey="version")

        schema_version_int = None
        if isinstance(ret, dict) and "schema" in ret:
            schema_version = ret["schema"]
            try:
                schema_version_int = int(schema_version)
            except (ValueError, TypeError):
                logger.warning(f"Schema version '{schema_version}' could not be converted to integer")
        if schema_version_int is None:
            logger.warning("Schema version not found in query result")
        logger.info("exit: _get_schema_ver_async")
        return schema_version_int

    except Exception as e:
        logger.error(f"Error getting schema version: {str(e)}")
        raise Exception(f"Failed to get schema version: {str(e)}")

def generate_schema_rep(conn: TigerGraphConnectionProxy, schema_ver: int = None, graphrag: bool = False) -> str:
    """Generate a schema representation for a TigerGraph connection.

    This function maintains an internal cache of schema representations keyed by
    schema version to avoid regenerating schemas unnecessarily.

    Args:
        conn (TigerGraphConnectionProxy): The TigerGraph connection
        schema_ver (int): The schema version
        graphrag (bool): Whether to include GraphRAG vertex and edge types
    Returns:
        str: The schema representation
    """

    # Get current schema version
    try:
        schema_ver = schema_ver if schema_ver is not None else get_schema_ver(conn)
    except Exception as e:
        logger.error(f"Error getting schema version: {str(e)}")
        schema_ver = _schema_cache.keys()[-1] if _schema_cache.keys() else 0

    # Check if we have a cached version for this schema version
    if schema_ver in _schema_cache:
        logger.info(f"Reusing cached schema rep for schema version {schema_ver}")
        return _schema_cache[schema_ver]

    # Get vertex and edge types
    verts = conn.getVertexTypes()
    edges = conn.getEdgeTypes()
    vertex_schema = []

    for vert in verts:
        if graphrag and vert in graphrag_vertex_types:
            continue
        primary_id = conn.getVertexType(vert)["PrimaryId"]["AttributeName"]
        attributes = "\n\t\t".join([attr["AttributeName"] + " of type " + attr["AttributeType"]["Name"] 
                                    for attr in conn.getVertexType(vert)["Attributes"]])
        if attributes == "":
            attributes = "No attributes"
        vertex_schema.append(f"{vert}\n\tPrimary Id Attribute: {primary_id}\n\tAttributes: \n\t\t{attributes}")

    edge_schema = []
    for edge in edges:
        if graphrag and edge in graphrag_edge_types:
            continue
        from_vertex = conn.getEdgeType(edge)["FromVertexTypeName"]
        to_vertex = conn.getEdgeType(edge)["ToVertexTypeName"]
        direction = "Directed" if conn.getEdgeType(edge)["IsDirected"] else "Undirected"
        #reverse_edge = conn.getEdgeType(edge)["Config"].get("REVERSE_EDGE")
        attributes = "\n\t\t".join([attr["AttributeName"] + " of type " + attr["AttributeType"]["Name"] 
                                    for attr in conn.getEdgeType(edge)["Attributes"]])
        if attributes == "":
            attributes = "No attributes"
        if from_vertex == "*" or to_vertex == "*":
            edge_pairs = conn.getEdgeType(edge)["EdgePairs"]
            for an_edge in edge_pairs:
                edge_info = f"""From Vertex: {an_edge["From"]}\n\tTo Vertex: {an_edge["To"]}"""
                edge_schema.append(f"""{edge}\n\t{edge_info}\n\tEdge direction: {direction}\n\tAttributes: \n\t\t{attributes}""")
        else:
            edge_info = f"""From Vertex: {from_vertex}\n\tTo Vertex: {to_vertex}"""
            edge_schema.append(f"""{edge}\n\t{edge_info}\n\tEdge direction: {direction}\n\tAttributes: \n\t\t{attributes}""")

    schema_rep = f"""
Vertex Types:
{chr(10).join(vertex_schema)}

Edge Types:
{chr(10).join(edge_schema)}
"""

    # Cache the result
    _schema_cache[schema_ver] = schema_rep

    return schema_rep

async def generate_schema_rep_async(conn: AsyncTigerGraphConnection, schema_ver: int = None, graphrag: bool = False) -> str:
    """Generate a schema representation for an async TigerGraph connection.

    This function maintains an internal cache of schema representations keyed by
    schema version to avoid regenerating schemas unnecessarily.

    Args:
        conn (AsyncTigerGraphConnection): The async TigerGraph connection
        schema_ver (int): The schema version
        graphrag (bool): Whether to include GraphRAG vertex and edge types
    Returns:
        str: The schema representation
    """
    # Get current schema version
    try:
        if schema_ver is None:
            schema_ver = await get_schema_ver_async(conn)
    except Exception as e:
        logger.error(f"Error getting schema version: {str(e)}")
        schema_ver = 0

    # Check if we have a cached version for this schema version
    if schema_ver in _schema_cache:
        logger.info(f"Reusing cached schema rep for schema version {schema_ver}")
        return _schema_cache[schema_ver]

    # Get vertex and edge types
    verts = await conn.getVertexTypes()
    edges = await conn.getEdgeTypes()
    vertex_schema = []

    for vert in verts:
        if graphrag and vert in graphrag_vertex_types:
            continue
        vertex_type = await conn.getVertexType(vert)
        primary_id = vertex_type["PrimaryId"]["AttributeName"]
        attributes = "\n\t\t".join([attr["AttributeName"] + " of type " + attr["AttributeType"]["Name"]
                                    for attr in vertex_type["Attributes"]])
        if attributes == "":
            attributes = "No attributes"
        vertex_schema.append(f"{vert}\n\tPrimary Id Attribute: {primary_id}\n\tAttributes: \n\t\t{attributes}")

    edge_schema = []
    for edge in edges:
        if graphrag and edge in graphrag_edge_types:
            continue
        edge_type = await conn.getEdgeType(edge)
        from_vertex = edge_type["FromVertexTypeName"]
        to_vertex = edge_type["ToVertexTypeName"]
        direction = "Directed" if edge_type["IsDirected"] else "Undirected"
        #reverse_edge = edge_type["Config"].get("REVERSE_EDGE")
        attributes = "\n\t\t".join([attr["AttributeName"] + " of type " + attr["AttributeType"]["Name"]
                                    for attr in edge_type["Attributes"]])
        if attributes == "":
            attributes = "No attributes"
        if from_vertex == "*" or to_vertex == "*":
            edge_pairs = edge_type["EdgePairs"]
            for an_edge in edge_pairs:
                edge_info = f"""From Vertex: {an_edge["From"]}\n\tTo Vertex: {an_edge["To"]}"""
                edge_schema.append(f"""{edge}\n\t{edge_info}\n\tEdge direction: {direction}\n\tAttributes: \n\t\t{attributes}""")
        else:
            edge_info = f"""From Vertex: {from_vertex}\n\tTo Vertex: {to_vertex}"""
            edge_schema.append(f"""{edge}\n\t{edge_info}\n\tEdge direction: {direction}\n\tAttributes: \n\t\t{attributes}""")

    schema_rep = f"""
Vertex Types:
{chr(10).join(vertex_schema)}

Edge Types:
{chr(10).join(edge_schema)}
"""

    # Cache the result
    _schema_cache[schema_ver] = schema_rep

    return schema_rep

def clear_schema_caches():
    """Clear all schema-related caches.

    This function can be called to clear both the schema representation cache
    and the vertex/edge types cache. Useful for testing or when you want to
    force fresh data retrieval.
    """
    global _schema_cache, _types_cache
    _schema_cache.clear()
    _types_cache.clear()
    logger.info("Schema caches cleared")