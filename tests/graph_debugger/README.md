This folder contains a reusable TigerGraph inspection utility for debugging graph contents.

It reads connection details from `configs/server_config.json`, connects to TigerGraph, and writes a timestamped report folder under `tests/graph_debugger/output/`.

Files written per run:

- `metadata.json`: run arguments and paths
- `graph_listing.json`: raw graph-listing diagnostics
- `graph_listing_ls.txt`: raw `ls` output when available
- `graph_listing_show_graph.txt`: raw `SHOW GRAPH *` output when available
- `inspection.json`: schema, counts, samples, and connectivity results for the target graph
- `report.md`: short human-readable summary

Run from the repo root:

```powershell
python tests/graph_debugger/run_graph_debug.py --list-graphs-only
```

```powershell
python tests/graph_debugger/run_graph_debug.py --graph test_123
```

If your graph label in TigerGraph Cloud looks like `test 123`, the actual graph name may still be something like `test_123`. Run `--list-graphs-only` first if you are unsure.
