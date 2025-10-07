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
from typing import List, Tuple
from common.metrics.tg_proxy import TigerGraphConnectionProxy
from common.db.connections import get_schema_ver

logger = logging.getLogger(__name__)

# Internal cache for schema representations
_schema_cache = {}

# Internal cache for vertex and edge types
_types_cache = {}


def get_vertex_and_edge_types(conn: TigerGraphConnectionProxy, schema_ver: int = None) -> Tuple[List[str], List[str]]:
    """Get lists of vertex types and edge types from a TigerGraph connection.
    
    This function maintains an internal cache of vertex and edge types keyed by
    schema version to avoid repeated database calls when the schema hasn't changed.
    
    Args:
        conn (TigerGraphConnectionProxy): The TigerGraph connection
        
    Returns:
        Tuple[List[str], List[str]]: A tuple containing lists of vertex types and edge types
    """
    # Get current schema version
    try:
        schema_ver = schema_ver if schema_ver is not None else get_schema_ver(conn)
    except Exception as e:
        logger.error(f"Error getting schema version: {str(e)}")
        schema_ver = list(_types_cache.keys())[-1] if _types_cache.keys() else 0
    
    # Check if we have a cached version for this schema version
    if schema_ver in _types_cache:
        logger.info(f"Reusing cached vertex and edge types for schema version {schema_ver}")
        return _types_cache[schema_ver]
    
    try:
        vertex_types = conn.getVertexTypes()
        edge_types = conn.getEdgeTypes()
        
        # Cache the result
        _types_cache[schema_ver] = (vertex_types, edge_types)
        
        return vertex_types, edge_types
    except Exception as e:
        logger.error(f"Error getting vertex and edge types: {str(e)}")
        return [], []


def generate_schema_rep(conn: TigerGraphConnectionProxy, schema_ver: int = None) -> str:
    """Generate a schema representation for a TigerGraph connection.
    
    This function maintains an internal cache of schema representations keyed by
    schema version to avoid regenerating schemas unnecessarily.
    
    Args:
        conn (TigerGraphConnectionProxy): The TigerGraph connection
        
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
        
    # Get vertex and edge types using the helper function
    verts, edges = get_vertex_and_edge_types(conn)
    vertex_schema = []
    
    for vert in verts:
        primary_id = conn.getVertexType(vert)["PrimaryId"]["AttributeName"]
        attributes = "\n\t\t".join([attr["AttributeName"] + " of type " + attr["AttributeType"]["Name"] 
                                    for attr in conn.getVertexType(vert)["Attributes"]])
        if attributes == "":
            attributes = "No attributes"
        vertex_schema.append(f"{vert}\n\tPrimary Id Attribute: {primary_id}\n\tAttributes: \n\t\t{attributes}")

    edge_schema = []
    for edge in edges:
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