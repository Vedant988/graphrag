import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyTigerGraph import TigerGraphConnection


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "server_config.json"
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "output"
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a TigerGraph graph and write a reusable debug report."
    )
    parser.add_argument(
        "--graph",
        help="Exact TigerGraph graph name to inspect. Quote it if needed.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to server_config.json",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Folder where timestamped report directories will be created",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=10,
        help="How many sample vertices/edges to collect per section",
    )
    parser.add_argument(
        "--list-graphs-only",
        action="store_true",
        help="Only connect and dump graph listing diagnostics",
    )
    return parser.parse_args()


def load_server_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def make_connection(db_config: dict[str, Any], graphname: str = "") -> TigerGraphConnection:
    kwargs: dict[str, Any] = {
        "host": db_config["hostname"],
        "username": db_config.get("username", ""),
        "password": db_config.get("password", ""),
        "graphname": graphname,
        "restppPort": db_config.get("restppPort", "9000"),
        "gsPort": db_config.get("gsPort", "14240"),
    }
    api_token = str(db_config.get("apiToken", "") or "").strip()
    if api_token:
        kwargs["apiToken"] = api_token
    return TigerGraphConnection(**kwargs)


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "unnamed"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def try_gsql(conn: TigerGraphConnection, statement: str) -> dict[str, Any]:
    try:
        return {"ok": True, "statement": statement, "result": conn.gsql(statement)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "statement": statement, "error": str(exc)}


def parse_graph_names(raw_listing: str) -> list[str]:
    patterns = [
        re.compile(r"(?im)^\s*graph\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
        re.compile(r"(?im)^\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\b"),
        re.compile(r"(?im)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in pattern.findall(raw_listing):
            if match not in found:
                found.append(match)
    return found


def normalize_graph_hint(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value).lower()


def suggest_graph_matches(requested: str, available: list[str]) -> list[str]:
    wanted = normalize_graph_hint(requested)
    matches = [name for name in available if normalize_graph_hint(name) == wanted]
    if matches:
        return matches
    return [name for name in available if wanted and wanted in normalize_graph_hint(name)]


def list_graphs(db_config: dict[str, Any]) -> dict[str, Any]:
    conn = make_connection(db_config, graphname="")
    ls_result = try_gsql(conn, "ls")
    show_graph_result = try_gsql(conn, "SHOW GRAPH *")
    raw_listing = "\n\n".join(
        str(part["result"])
        for part in (ls_result, show_graph_result)
        if part.get("ok")
    )
    parsed = parse_graph_names(raw_listing)
    return {
        "ls": ls_result,
        "show_graph": show_graph_result,
        "parsed_graph_names": parsed,
    }


def safe_call(section: str, fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return {"ok": True, "section": section, "result": fn(*args, **kwargs)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "section": section, "error": str(exc)}


def sample_vertices(conn: TigerGraphConnection, vertex_types: list[str], limit: int) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for vertex_type in vertex_types:
        samples[vertex_type] = safe_call(
            f"sample_vertices:{vertex_type}",
            conn.getVertices,
            vertex_type,
            limit=limit,
        )
    return samples


def sample_relationship_edges(conn: TigerGraphConnection, entity_samples: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(entity_samples, list):
        return []
    edges: list[dict[str, Any]] = []
    for entity in entity_samples[:limit]:
        if not isinstance(entity, dict):
            continue
        vertex_id = entity.get("v_id") or entity.get("id")
        if not vertex_id:
            continue
        result = safe_call(
            f"relationship_edges:{vertex_id}",
            conn.getEdges,
            "Entity",
            vertex_id,
            edgeType="RELATIONSHIP",
            limit=limit,
        )
        edges.append({"entity_id": vertex_id, "edges": result})
    return edges


def inspect_graph(db_config: dict[str, Any], graphname: str, sample_limit: int) -> dict[str, Any]:
    conn = make_connection(db_config, graphname=graphname)
    connectivity = try_gsql(conn, f"USE GRAPH {graphname}\nls")

    if not connectivity["ok"]:
        return {
            "graphname": graphname,
            "connectivity": connectivity,
        }

    schema_info = safe_call("schema", conn.getSchema)
    vertex_counts = safe_call("vertex_count", conn.getVertexCount, "*")
    edge_counts = safe_call("edge_count", conn.getEdgeCount, "*")
    vertex_stats = safe_call("vertex_stats", conn.getVertexStats, "*", skipNA=True)

    schema_result = schema_info.get("result", {}) if schema_info.get("ok") else {}
    vertex_types = [
        item.get("Name")
        for item in schema_result.get("VertexTypes", [])
        if isinstance(item, dict) and item.get("Name")
    ]
    preferred_order = [
        "Entity",
        "Document",
        "DocumentChunk",
        "Community",
        "RelationshipType",
        "EntityType",
        "Content",
    ]
    ordered_vertex_types = [name for name in preferred_order if name in vertex_types]
    ordered_vertex_types.extend(name for name in vertex_types if name not in ordered_vertex_types)

    vertex_samples = sample_vertices(conn, ordered_vertex_types[: min(len(ordered_vertex_types), 8)], sample_limit)
    entity_result = vertex_samples.get("Entity", {})
    entity_samples = entity_result.get("result") if entity_result.get("ok") else []
    relationship_edge_samples = sample_relationship_edges(conn, entity_samples, sample_limit)

    return {
        "graphname": graphname,
        "connectivity": connectivity,
        "schema": schema_info,
        "vertex_counts": vertex_counts,
        "edge_counts": edge_counts,
        "vertex_stats": vertex_stats,
        "vertex_samples": vertex_samples,
        "relationship_edge_samples": relationship_edge_samples,
    }


def build_markdown_report(
    requested_graph: str | None,
    graph_listing: dict[str, Any],
    inspection: dict[str, Any] | None,
    config_path: Path,
    sample_limit: int,
) -> str:
    lines = [
        "# Graph Debug Report",
        "",
        f"- Generated at (UTC): `{utc_timestamp()}`",
        f"- Config: `{config_path}`",
        f"- Requested graph: `{requested_graph or ''}`",
        f"- Sample limit: `{sample_limit}`",
        "",
        "## Graph Listing",
        "",
        f"- Parsed graph names: `{', '.join(graph_listing.get('parsed_graph_names', [])) or 'none parsed'}`",
    ]

    if requested_graph and inspection is not None and not inspection.get("connectivity", {}).get("ok"):
        suggestions = suggest_graph_matches(requested_graph, graph_listing.get("parsed_graph_names", []))
        lines.extend(
            [
                "",
                "## Connectivity",
                "",
                f"- Status: `failed`",
                f"- Error: `{inspection['connectivity'].get('error', 'unknown error')}`",
                f"- Suggested graph names: `{', '.join(suggestions) or 'none'}`",
            ]
        )
        return "\n".join(lines) + "\n"

    if inspection is None:
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "",
            "## Connectivity",
            "",
            f"- Status: `{'ok' if inspection.get('connectivity', {}).get('ok') else 'failed'}`",
            "",
        ]
    )

    schema_result = inspection.get("schema", {}).get("result", {}) if inspection.get("schema", {}).get("ok") else {}
    vertex_type_names = [
        item.get("Name")
        for item in schema_result.get("VertexTypes", [])
        if isinstance(item, dict) and item.get("Name")
    ]
    edge_type_names = [
        item.get("Name")
        for item in schema_result.get("EdgeTypes", [])
        if isinstance(item, dict) and item.get("Name")
    ]

    lines.extend(
        [
            "## Schema",
            "",
            f"- Vertex types: `{', '.join(vertex_type_names) or 'none found'}`",
            f"- Edge types: `{', '.join(edge_type_names) or 'none found'}`",
            "",
            "## Counts",
            "",
            f"- Vertex counts captured: `{inspection.get('vertex_counts', {}).get('ok', False)}`",
            f"- Edge counts captured: `{inspection.get('edge_counts', {}).get('ok', False)}`",
        ]
    )

    vertex_counts_result = inspection.get("vertex_counts", {}).get("result")
    edge_counts_result = inspection.get("edge_counts", {}).get("result")
    if vertex_counts_result is not None:
        lines.append(f"- Vertex count summary: `{json.dumps(vertex_counts_result, ensure_ascii=True)}`")
    if edge_counts_result is not None:
        lines.append(f"- Edge count summary: `{json.dumps(edge_counts_result, ensure_ascii=True)}`")

    lines.extend(
        [
            "",
            "## Samples",
            "",
        ]
    )

    for vertex_type, payload in inspection.get("vertex_samples", {}).items():
        if not payload.get("ok"):
            lines.append(f"- `{vertex_type}` sample failed: `{payload.get('error', 'unknown error')}`")
            continue
        sample_count = len(payload.get("result", [])) if isinstance(payload.get("result"), list) else 0
        lines.append(f"- `{vertex_type}` sample rows: `{sample_count}`")

    relationship_samples = inspection.get("relationship_edge_samples", [])
    if relationship_samples:
        lines.append(f"- Relationship edge probes: `{len(relationship_samples)}`")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    server_config = load_server_config(config_path)
    db_config = server_config["db_config"]
    graph_listing = list_graphs(db_config)

    requested_graph = args.graph
    inspection: dict[str, Any] | None = None

    if args.list_graphs_only:
        requested_graph = requested_graph or ""
    elif requested_graph:
        inspection = inspect_graph(db_config, requested_graph, args.sample_limit)
    else:
        print("No graph provided. Use --graph <graphname> or --list-graphs-only.", file=sys.stderr)
        return 2

    report_key = slugify(requested_graph or "graph_listing")
    report_dir = output_root / f"{report_key}_{utc_timestamp()}"
    report_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "requested_graph": requested_graph,
        "config_path": str(config_path),
        "output_dir": str(report_dir),
        "sample_limit": args.sample_limit,
        "list_graphs_only": args.list_graphs_only,
    }

    write_json(report_dir / "metadata.json", metadata)
    write_json(report_dir / "graph_listing.json", graph_listing)

    if graph_listing.get("ls", {}).get("ok"):
        write_text(report_dir / "graph_listing_ls.txt", str(graph_listing["ls"]["result"]))
    if graph_listing.get("show_graph", {}).get("ok"):
        write_text(report_dir / "graph_listing_show_graph.txt", str(graph_listing["show_graph"]["result"]))

    if inspection is not None:
        write_json(report_dir / "inspection.json", inspection)

    markdown = build_markdown_report(
        requested_graph=requested_graph,
        graph_listing=graph_listing,
        inspection=inspection,
        config_path=config_path,
        sample_limit=args.sample_limit,
    )
    write_text(report_dir / "report.md", markdown)

    print(f"Report written to: {report_dir}")
    if graph_listing.get("parsed_graph_names"):
        print("Parsed graphs:", ", ".join(graph_listing["parsed_graph_names"]))
    if inspection is not None and not inspection.get("connectivity", {}).get("ok"):
        suggestions = suggest_graph_matches(requested_graph or "", graph_listing.get("parsed_graph_names", []))
        if suggestions:
            print("Suggested graph names:", ", ".join(suggestions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
