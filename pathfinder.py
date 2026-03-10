"""
pathfinder.py
-------------
Shortest path traversal algorithms.

Supports:
  - Single start → single end   (Dijkstra)
  - Single start → multiple ends (merged roadmap with shared prerequisites)
"""

import networkx as nx
from collections import defaultdict


# ──────────────────────────────────────────────
# Single endpoint
# ──────────────────────────────────────────────

def shortest_path(G: nx.DiGraph, source: str, target: str) -> dict:
    """
    Find the shortest (lowest-weight) path from source to target using Dijkstra.

    Returns:
        {
            "path": [node_id, ...],
            "total_weight": int,
            "found": bool,
            "error": str | None
        }
    """
    try:
        path = nx.dijkstra_path(G, source, target, weight="weight")
        cost = nx.dijkstra_path_length(G, source, target, weight="weight")
        return {"path": path, "total_weight": cost, "found": True, "error": None}
    except nx.NetworkXNoPath:
        return {"path": [], "total_weight": 0, "found": False,
                "error": f"No path found from '{_label(G, source)}' to '{_label(G, target)}'."}
    except nx.NodeNotFound as e:
        return {"path": [], "total_weight": 0, "found": False, "error": str(e)}


# ──────────────────────────────────────────────
# Multiple endpoints
# ──────────────────────────────────────────────

def multi_endpoint_roadmap(G: nx.DiGraph, source: str, targets: list[str]) -> dict:
    """
    Generate a unified roadmap that reaches ALL target nodes from source.

    Strategy:
      1. Run Dijkstra independently from source → each target.
      2. Merge all path nodes into a subgraph.
      3. Topologically sort the merged subgraph so prerequisites always
         appear before the topics that depend on them.
      4. Mark which nodes are shared prerequisites vs. target-specific.

    Returns:
        {
            "individual_paths": {target_id: {"path": [...], "total_weight": int, "found": bool}},
            "merged_nodes":     [node_id, ...],   # in topological order
            "shared_nodes":     {node_id, ...},   # visited by 2+ paths
            "target_nodes":     {node_id, ...},
            "subgraph":         nx.DiGraph,
            "all_found":        bool,
            "errors":           [str, ...]
        }
    """
    individual_paths = {}
    all_path_nodes = []
    errors = []

    for target in targets:
        result = shortest_path(G, source, target)
        individual_paths[target] = result
        if result["found"]:
            all_path_nodes.append(result["path"])
        else:
            errors.append(result["error"])

    if not all_path_nodes:
        return {
            "individual_paths": individual_paths,
            "merged_nodes": [],
            "shared_nodes": set(),
            "target_nodes": set(targets),
            "subgraph": nx.DiGraph(),
            "all_found": False,
            "errors": errors,
        }

    # Count how many paths each node appears in
    node_count = defaultdict(int)
    for path in all_path_nodes:
        for node in path:
            node_count[node] += 1

    shared_nodes = {n for n, c in node_count.items() if c > 1}

    # Build merged subgraph from all path nodes & edges
    all_nodes_set = set()
    for path in all_path_nodes:
        all_nodes_set.update(path)

    subgraph = G.subgraph(all_nodes_set).copy()

    # Topological sort (respects prerequisite ordering)
    try:
        topo_order = list(nx.topological_sort(subgraph))
    except nx.NetworkXUnfeasible:
        # Cycle detected — fall back to merging paths in order
        seen = set()
        topo_order = []
        for path in all_path_nodes:
            for n in path:
                if n not in seen:
                    topo_order.append(n)
                    seen.add(n)

    return {
        "individual_paths": individual_paths,
        "merged_nodes": topo_order,
        "shared_nodes": shared_nodes,
        "target_nodes": set(targets),
        "subgraph": subgraph,
        "all_found": len(errors) == 0,
        "errors": errors,
    }


# ──────────────────────────────────────────────
# Greedy multi-target (visit all, minimise total steps)
# ──────────────────────────────────────────────

def greedy_multi_target(G: nx.DiGraph, source: str, targets: list[str]) -> dict:
    """
    Greedy nearest-neighbour traversal: from current position,
    always visit the closest unvisited target next.

    Useful when the user wants an ORDERED sequence of goal completions
    rather than a merged curriculum.

    Returns:
        {
            "visit_order": [target_id, ...],
            "segments": [{"from": id, "to": id, "path": [...], "weight": int}],
            "total_weight": int,
            "all_found": bool,
            "errors": [str]
        }
    """
    remaining = list(targets)
    current = source
    visit_order = []
    segments = []
    total_weight = 0
    errors = []

    while remaining:
        best_target = None
        best_result = None
        best_cost = float("inf")

        for t in remaining:
            result = shortest_path(G, current, t)
            if result["found"] and result["total_weight"] < best_cost:
                best_cost = result["total_weight"]
                best_target = t
                best_result = result

        if best_target is None:
            # No reachable targets remain
            for t in remaining:
                errors.append(f"Cannot reach '{_label(G, t)}' from '{_label(G, current)}'.")
            break

        visit_order.append(best_target)
        segments.append({
            "from": current,
            "to": best_target,
            "path": best_result["path"],
            "weight": best_result["total_weight"],
        })
        total_weight += best_cost
        current = best_target
        remaining.remove(best_target)

    return {
        "visit_order": visit_order,
        "segments": segments,
        "total_weight": total_weight,
        "all_found": len(errors) == 0,
        "errors": errors,
    }


# ──────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────

def _label(G: nx.DiGraph, node_id: str) -> str:
    return G.nodes[node_id].get("label", node_id) if node_id in G else node_id
