"""
output.py
---------
Formats and displays pathfinder results in a readable roadmap.
Also supports JSON export.
"""

import json
import networkx as nx


CATEGORY_ICONS = {
    "essential":            "🔵",
    "optional_recommended": "🟣",
    "optional":             "🟡",
    "unknown":              "⚪",
}

CATEGORY_LABELS = {
    "essential":            "Essential",
    "optional_recommended": "Optional but Recommended",
    "optional":             "Optional",
    "unknown":              "Unknown",
}


def _label(G: nx.DiGraph, node_id: str) -> str:
    return G.nodes[node_id].get("label", node_id) if node_id in G else node_id


def _cat(G: nx.DiGraph, node_id: str) -> str:
    return G.nodes[node_id].get("category", "unknown") if node_id in G else "unknown"


# ──────────────────────────────────────────────
# Single path
# ──────────────────────────────────────────────

def print_single_path(G: nx.DiGraph, result: dict, source_label: str, target_label: str):
    print()
    print("=" * 60)
    print(f"  📍 ROADMAP: {source_label}  →  {target_label}")
    print("=" * 60)

    if not result["found"]:
        print(f"\n  ❌ {result['error']}\n")
        return

    path = result["path"]
    print(f"\n  Total steps : {len(path)}")
    print(f"  Path weight : {result['total_weight']}")
    print()

    for i, node_id in enumerate(path, 1):
        label = _label(G, node_id)
        cat = _cat(G, node_id)
        icon = CATEGORY_ICONS.get(cat, "⚪")
        cat_label = CATEGORY_LABELS.get(cat, cat)
        connector = "└──▶" if i == len(path) else "├──▶"
        print(f"  Step {i:>2}  {connector}  {icon} {label}")
        print(f"           │       [{cat_label}]")
        if i < len(path):
            print(f"           │")

    print()
    print("=" * 60)
    print()


# ──────────────────────────────────────────────
# Multi-endpoint merged roadmap
# ──────────────────────────────────────────────

def print_multi_path(G: nx.DiGraph, result: dict, source_label: str, target_labels: list[str]):
    print()
    print("=" * 60)
    print(f"  📍 MERGED ROADMAP")
    print(f"     From : {source_label}")
    print(f"     To   : {', '.join(target_labels)}")
    print("=" * 60)

    if result["errors"]:
        print()
        for err in result["errors"]:
            print(f"  ⚠️  {err}")

    merged = result["merged_nodes"]
    shared = result["shared_nodes"]
    targets = result["target_nodes"]

    if not merged:
        print("\n  ❌ No valid paths found.\n")
        return

    print(f"\n  Total unique steps : {len(merged)}")
    print(f"  Shared nodes       : {len(shared)}")
    print()
    print("  Legend:")
    print("    🔵 Essential   🟣 Opt.Recommended   🟡 Optional")
    print("    ★  = Goal node    ◈  = Shared prerequisite")
    print()

    for i, node_id in enumerate(merged, 1):
        label = _label(G, node_id)
        cat = _cat(G, node_id)
        icon = CATEGORY_ICONS.get(cat, "⚪")
        is_target = node_id in targets
        is_shared = node_id in shared

        tag = ""
        if is_target:
            tag += " ★ GOAL"
        if is_shared and not is_target:
            tag += " ◈ shared"

        connector = "└──▶" if i == len(merged) else "├──▶"
        print(f"  Step {i:>2}  {connector}  {icon} {label}{tag}")
        if i < len(merged):
            print(f"           │")

    print()
    print("  ─── Individual Path Summary ───")
    for tid, path_result in result["individual_paths"].items():
        t_label = _label(G, tid)
        if path_result["found"]:
            print(f"  ✅  {t_label}  ({len(path_result['path'])} steps, weight {path_result['total_weight']})")
        else:
            print(f"  ❌  {t_label}  — {path_result['error']}")

    print()
    print("=" * 60)
    print()


# ──────────────────────────────────────────────
# Greedy ordered visit
# ──────────────────────────────────────────────

def print_greedy_path(G: nx.DiGraph, result: dict, source_label: str):
    print()
    print("=" * 60)
    print(f"  📍 ORDERED GOAL TRAVERSAL (Greedy Nearest-Neighbour)")
    print(f"     Start : {source_label}")
    print("=" * 60)

    if result["errors"]:
        print()
        for err in result["errors"]:
            print(f"  ⚠️  {err}")

    if not result["segments"]:
        print("\n  ❌ No valid paths found.\n")
        return

    print(f"\n  Goals visited : {len(result['visit_order'])}")
    print(f"  Total weight  : {result['total_weight']}")
    print()

    step = 1
    for seg in result["segments"]:
        from_label = _label(G, seg["from"])
        to_label = _label(G, seg["to"])
        print(f"  ── Segment: {from_label}  →  {to_label} (weight {seg['weight']}) ──")
        for node_id in seg["path"]:
            label = _label(G, node_id)
            cat = _cat(G, node_id)
            icon = CATEGORY_ICONS.get(cat, "⚪")
            print(f"  Step {step:>2}  ──▶  {icon} {label}")
            step += 1
        print()

    print("=" * 60)
    print()


# ──────────────────────────────────────────────
# Topic list
# ──────────────────────────────────────────────

def print_topic_list(topics: list[dict]):
    print()
    print("=" * 60)
    print("  📚 ALL AVAILABLE TOPICS")
    print("=" * 60)
    print()
    for t in topics:
        cat = t["category"]
        icon = CATEGORY_ICONS.get(cat, "⚪")
        print(f"  {icon}  {t['label']}")
        print(f"       in:{t['in_degree']}  out:{t['out_degree']}  [{CATEGORY_LABELS.get(cat, cat)}]")
    print()
    print(f"  Total: {len(topics)} topics")
    print()


# ──────────────────────────────────────────────
# JSON export
# ──────────────────────────────────────────────

def export_json(G: nx.DiGraph, result: dict, mode: str, filepath: str):
    """Export roadmap result to a JSON file."""

    def node_info(node_id):
        return {
            "id": node_id,
            "label": _label(G, node_id),
            "category": _cat(G, node_id),
        }

    output = {"mode": mode}

    if mode == "single":
        output["path"] = [node_info(n) for n in result.get("path", [])]
        output["total_weight"] = result.get("total_weight", 0)
        output["found"] = result.get("found", False)

    elif mode == "multi":
        output["merged_roadmap"] = [node_info(n) for n in result.get("merged_nodes", [])]
        output["shared_prerequisites"] = [node_info(n) for n in result.get("shared_nodes", set())]
        output["individual_paths"] = {
            _label(G, tid): {
                "found": pr["found"],
                "total_weight": pr["total_weight"],
                "path": [node_info(n) for n in pr.get("path", [])],
            }
            for tid, pr in result.get("individual_paths", {}).items()
        }

    elif mode == "greedy":
        output["segments"] = [
            {
                "from": _label(G, s["from"]),
                "to": _label(G, s["to"]),
                "weight": s["weight"],
                "path": [node_info(n) for n in s["path"]],
            }
            for s in result.get("segments", [])
        ]
        output["total_weight"] = result.get("total_weight", 0)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  💾 Exported to: {filepath}\n")
