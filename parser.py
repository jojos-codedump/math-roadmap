"""
parser.py
---------
Parses a .drawio XML file and extracts:
  - Nodes (swimlane containers = topic groups, and leaf cells = books/resources)
  - Edges (directed connections between topics)

Returns a clean graph-ready structure.
"""

import xml.etree.ElementTree as ET
import re
import html


def strip_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities from node labels."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_drawio(filepath: str) -> dict:
    """
    Parse a .drawio file and return a structured representation.

    Returns:
        {
            "nodes": {
                id: {
                    "id": str,
                    "label": str,
                    "parent": str | None,
                    "is_container": bool,
                    "style": str,
                    "category": str   # "essential" | "optional" | "optional_recommended"
                }
            },
            "edges": [
                {
                    "source": str,
                    "target": str,
                    "bidirectional": bool,
                    "style": str
                }
            ]
        }
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Locate the root cell container
    all_cells = root.findall(".//{http://}mxCell") or root.findall(".//mxCell")

    nodes = {}
    edges = []

    for cell in all_cells:
        cell_id = cell.get("id", "")
        value = cell.get("value", "")
        style = cell.get("style", "")
        parent = cell.get("parent", "")
        vertex = cell.get("vertex")
        edge = cell.get("edge")
        source = cell.get("source", "")
        target = cell.get("target", "")

        # Skip root structural cells
        if cell_id in ("0", "1"):
            continue

        label = strip_html(value)

        # Determine category based on style colors
        category = _infer_category(style)

        if vertex == "1" and label:
            is_container = "swimlane" in style
            nodes[cell_id] = {
                "id": cell_id,
                "label": label,
                "parent": parent if parent not in ("0", "1") else None,
                "is_container": is_container,
                "style": style,
                "category": category,
            }

        elif edge == "1":
            if source and target:
                is_bidirectional = "startArrow=classic" in style and "endArrow=classic" in style
                edges.append({
                    "source": source,
                    "target": target,
                    "bidirectional": is_bidirectional,
                    "style": style,
                })

    return {"nodes": nodes, "edges": edges}


def _infer_category(style: str) -> str:
    """Infer topic category from cell fill color in style string."""
    if "fillColor=#dae8fc" in style:
        return "essential"
    elif "fillColor=#fff2cc" in style:
        return "optional"
    elif "fillColor=#e1d5e7" in style:
        return "optional_recommended"
    return "unknown"


def get_topic_nodes(parsed: dict) -> dict:
    """
    Filter to only top-level swimlane containers (the actual topic nodes).
    These are the nodes with no parent other than root, and is_container=True.
    """
    nodes = parsed["nodes"]
    topic_nodes = {}

    for nid, node in nodes.items():
        # Top-level topics: swimlane containers whose parent is root (None)
        if node["is_container"] and node["parent"] is None:
            topic_nodes[nid] = node

    return topic_nodes


def get_topic_edges(parsed: dict, topic_node_ids: set) -> list:
    """
    Filter edges to only those connecting top-level topic nodes.
    Edges may also originate from child cells inside a swimlane —
    resolve those back to their parent container.
    """
    nodes = parsed["nodes"]

    def resolve_to_topic(cell_id: str) -> str | None:
        """Walk up parent chain to find the top-level topic container."""
        if cell_id in topic_node_ids:
            return cell_id
        node = nodes.get(cell_id)
        if node and node["parent"] and node["parent"] in topic_node_ids:
            return node["parent"]
        # Two levels deep
        if node and node["parent"]:
            grandparent_node = nodes.get(node["parent"])
            if grandparent_node and grandparent_node["parent"] in topic_node_ids:
                return grandparent_node["parent"]
        return None

    topic_edges = []
    seen = set()

    for edge in parsed["edges"]:
        src = resolve_to_topic(edge["source"])
        tgt = resolve_to_topic(edge["target"])

        if src and tgt and src != tgt:
            key = (src, tgt)
            if key not in seen:
                seen.add(key)
                topic_edges.append({
                    "source": src,
                    "target": tgt,
                    "bidirectional": edge["bidirectional"],
                    "style": edge["style"],
                })
                if edge["bidirectional"]:
                    rev_key = (tgt, src)
                    if rev_key not in seen:
                        seen.add(rev_key)
                        topic_edges.append({
                            "source": tgt,
                            "target": src,
                            "bidirectional": True,
                            "style": edge["style"],
                        })

    return topic_edges
