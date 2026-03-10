"""
graph_builder.py
----------------
Constructs a NetworkX directed graph from parsed .drawio data.

Edge weights:
  - Essential edges   (blue,  #dae8fc) → weight 1
  - Opt. Recommended  (purple,#e1d5e7) → weight 2
  - Optional          (yellow,#fff2cc) → weight 3

Lower weight = higher priority in shortest path.
"""

import networkx as nx


CATEGORY_WEIGHT = {
    "essential": 1,
    "optional_recommended": 2,
    "optional": 3,
    "unknown": 2,
}


def build_graph(topic_nodes: dict, topic_edges: list) -> nx.DiGraph:
    """
    Build and return a directed weighted NetworkX graph.

    Node attributes stored:
      - label (str)
      - category (str)

    Edge attributes stored:
      - weight (int)
      - bidirectional (bool)
    """
    G = nx.DiGraph()

    for nid, node in topic_nodes.items():
        G.add_node(
            nid,
            label=node["label"],
            category=node["category"],
        )

    for edge in topic_edges:
        src = edge["source"]
        tgt = edge["target"]
        if src not in G or tgt not in G:
            continue

        # Infer edge weight from style color
        weight = _infer_edge_weight(edge["style"])

        G.add_edge(src, tgt, weight=weight, bidirectional=edge["bidirectional"])

    return G


def _infer_edge_weight(style: str) -> int:
    """Assign weight based on edge fill/stroke color."""
    if "fillColor=#dae8fc" in style or "strokeColor=#6c8ebf" in style:
        return 1
    elif "fillColor=#e1d5e7" in style or "strokeColor=#9673a6" in style:
        return 2
    elif "fillColor=#fff2cc" in style or "strokeColor=#d6b656" in style:
        return 3
    return 2


def find_node_by_label(G: nx.DiGraph, label: str) -> str | None:
    """
    Find a node ID by matching its label (case-insensitive, partial match).
    Returns the best match node ID, or None.
    """
    label_lower = label.lower()
    exact = []
    partial = []

    for nid, data in G.nodes(data=True):
        node_label = data.get("label", "").lower()
        if node_label == label_lower:
            exact.append(nid)
        elif label_lower in node_label or node_label in label_lower:
            partial.append(nid)

    if exact:
        return exact[0]
    if partial:
        # Return shortest label match (most specific)
        partial.sort(key=lambda n: len(G.nodes[n]["label"]))
        return partial[0]
    return None


def list_all_topics(G: nx.DiGraph) -> list[dict]:
    """Return sorted list of all topic names in the graph."""
    topics = []
    for nid, data in G.nodes(data=True):
        topics.append({
            "id": nid,
            "label": data.get("label", ""),
            "category": data.get("category", ""),
            "out_degree": G.out_degree(nid),
            "in_degree": G.in_degree(nid),
        })
    topics.sort(key=lambda t: t["label"])
    return topics
