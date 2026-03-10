"""
main.py
-------
CLI entrypoint for the Mathematics Roadmap Pathfinder.

Usage examples:

  # List all available topics
  python main.py --file roadmap.drawio --list

  # Single endpoint
  python main.py --file roadmap.drawio --start "Calculus" --end "Real Analysis"

  # Multiple endpoints (merged curriculum)
  python main.py --file roadmap.drawio --start "Calculus" --end "Real Analysis" "Algebraic Topology"

  # Multiple endpoints (greedy ordered visit)
  python main.py --file roadmap.drawio --start "Calculus" --end "Real Analysis" "Algebraic Topology" --mode greedy

  # Export result to JSON
  python main.py --file roadmap.drawio --start "Calculus" --end "Real Analysis" --export result.json
"""

import argparse
import sys

from parser import parse_drawio, get_topic_nodes, get_topic_edges
from graph_builder import build_graph, find_node_by_label, list_all_topics
from pathfinder import shortest_path, multi_endpoint_roadmap, greedy_multi_target
from output import (
    print_single_path,
    print_multi_path,
    print_greedy_path,
    print_topic_list,
    export_json,
)


def main():
    parser = argparse.ArgumentParser(
        description="🧮 Mathematics Roadmap Shortest Path Finder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--file", "-f",
        required=True,
        help="Path to the .drawio file (e.g. mathematics-roadmap.drawio)",
    )
    parser.add_argument(
        "--start", "-s",
        help="Starting topic name (partial match supported)",
    )
    parser.add_argument(
        "--end", "-e",
        nargs="+",
        help="Target topic name(s). Provide multiple for multi-endpoint mode.",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["auto", "single", "multi", "greedy"],
        default="auto",
        help=(
            "Path mode:\n"
            "  auto    → single if 1 target, multi if >1 (default)\n"
            "  single  → Dijkstra to one target\n"
            "  multi   → merged curriculum reaching all targets\n"
            "  greedy  → nearest-neighbour ordered goal visits"
        ),
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available topic nodes and exit.",
    )
    parser.add_argument(
        "--export",
        metavar="OUTPUT.json",
        help="Export the roadmap result to a JSON file.",
    )

    args = parser.parse_args()

    # ── No start/end args → launch TUI ───────────────────────────
    if not args.start and not args.end and not args.list:
        from tui import launch
        launch(args.file)
        return

    # ── Load and build graph ──────────────────────────────────────
    print(f"\n  🔍 Loading: {args.file}")
    try:
        parsed = parse_drawio(args.file)
    except FileNotFoundError:
        print(f"\n  ❌ File not found: {args.file}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  ❌ Failed to parse file: {e}")
        sys.exit(1)

    topic_nodes = get_topic_nodes(parsed)
    topic_edges = get_topic_edges(parsed, set(topic_nodes.keys()))
    G = build_graph(topic_nodes, topic_edges)

    print(f"  ✅ Graph loaded: {G.number_of_nodes()} topics, {G.number_of_edges()} connections")

    # ── List mode ─────────────────────────────────────────────────
    if args.list:
        topics = list_all_topics(G)
        print_topic_list(topics)
        return

    # ── Require start and end ─────────────────────────────────────
    if not args.start or not args.end:
        print("\n  ❌ Please provide --start and --end (or use --list to see topics).\n")
        parser.print_help()
        sys.exit(1)

    # ── Resolve node IDs ──────────────────────────────────────────
    source_id = find_node_by_label(G, args.start)
    if not source_id:
        print(f"\n  ❌ Could not find topic matching: '{args.start}'")
        print("     Use --list to see all available topics.")
        sys.exit(1)

    source_label = G.nodes[source_id]["label"]
    print(f"  📌 Start  : {source_label}")

    target_ids = []
    target_labels = []
    for t in args.end:
        tid = find_node_by_label(G, t)
        if not tid:
            print(f"  ⚠️  Could not find topic matching: '{t}' — skipping.")
        else:
            target_ids.append(tid)
            target_labels.append(G.nodes[tid]["label"])
            print(f"  🎯 Target : {G.nodes[tid]['label']}")

    if not target_ids:
        print("\n  ❌ No valid target topics found.\n")
        sys.exit(1)

    # ── Determine mode ────────────────────────────────────────────
    mode = args.mode
    if mode == "auto":
        mode = "single" if len(target_ids) == 1 else "multi"

    # ── Run pathfinder ────────────────────────────────────────────
    if mode == "single":
        result = shortest_path(G, source_id, target_ids[0])
        print_single_path(G, result, source_label, target_labels[0])
        if args.export and result["found"]:
            export_json(G, result, "single", args.export)

    elif mode == "multi":
        result = multi_endpoint_roadmap(G, source_id, target_ids)
        print_multi_path(G, result, source_label, target_labels)
        if args.export:
            export_json(G, result, "multi", args.export)

    elif mode == "greedy":
        result = greedy_multi_target(G, source_id, target_ids)
        print_greedy_path(G, result, source_label)
        if args.export:
            export_json(G, result, "greedy", args.export)


if __name__ == "__main__":
    main()
