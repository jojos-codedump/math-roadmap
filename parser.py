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


def parse_book_label(raw: str) -> dict:
    """
    Split a raw book cell value into title + author.
    Handles both:
      - Title<br><b>Author</b>
      - <div>Title</div><div><b>Author</b></div>
    """
    raw = html.unescape(raw)

    # Extract bold text as author
    author_match = re.search(r"<b[^>]*>(.*?)</b>", raw, re.DOTALL)
    author = strip_html(author_match.group(1)) if author_match else ""

    # Remove the bold block, then strip remaining HTML for title
    title_raw = re.sub(r"<b[^>]*>.*?</b>", "", raw, flags=re.DOTALL)
    title = strip_html(title_raw)

    return {"title": title, "author": author}


def get_topic_books(parsed: dict, topic_node_ids: set) -> dict:
    """
    For each top-level topic node, collect its direct child book/resource cells.

    Returns:
        {topic_id: [{"title": str, "author": str, "category": str}, ...]}
    """
    nodes = parsed["nodes"]
    books: dict = {tid: [] for tid in topic_node_ids}

    for nid, node in nodes.items():
        if node["is_container"] or not node["label"]:
            continue

        parent = node["parent"]
        if not parent:
            continue

        # Direct child of a topic
        if parent in topic_node_ids:
            book = parse_book_label(
                # Re-parse from the already-stored label isn't ideal but works
                # because strip_html already ran; we re-derive from label here
                node["label"]
            )
            # label at this point is already stripped; split on first word chunk
            # that looks like an author (stored in node["label"] as "Title Author")
            # Better: store raw value too — but we didn't. Use the stripped label
            # and infer split from category (book cells never have children).
            # Since strip_html already merged title+author, re-parse from raw:
            books[parent].append({
                "title": node["label"],   # full stripped text (title + author merged)
                "author": "",
                "category": node["category"],
            })
            continue

        # Child of a sub-swimlane that is itself inside a topic
        parent_node = nodes.get(parent)
        if parent_node and parent_node["parent"] in topic_node_ids:
            topic_id = parent_node["parent"]
            books[topic_id].append({
                "title": node["label"],
                "author": "",
                "category": node["category"],
            })

    return books


def get_topic_books_rich(parsed_path: str, topic_node_ids: set) -> dict:
    """
    Re-parse the .drawio file a second time to get properly split
    title/author for each book, without losing data from strip_html.

    Returns:
        {topic_id: [{"title": str, "author": str, "category": str}]}
    """
    tree = ET.parse(parsed_path)
    root = tree.getroot()
    all_cells = root.findall(".//mxCell")

    # Build a quick parent→topic map (including grandparent resolution)
    # We need node id → parent id from the full cell list
    id_to_parent: dict = {}
    id_to_style: dict  = {}
    id_to_container: dict = {}
    for cell in all_cells:
        cid = cell.get("id", "")
        style = cell.get("style", "")
        parent = cell.get("parent", "")
        if cid in ("0", "1"):
            continue
        id_to_parent[cid] = parent
        id_to_style[cid]  = style
        id_to_container[cid] = "swimlane" in style

    def resolve_topic(cid: str):
        p = id_to_parent.get(cid, "")
        if p in topic_node_ids:
            return p
        gp = id_to_parent.get(p, "")
        if gp in topic_node_ids:
            return gp
        return None

    books: dict = {tid: [] for tid in topic_node_ids}

    for cell in all_cells:
        cid   = cell.get("id", "")
        value = cell.get("value", "")
        style = cell.get("style", "")
        vertex = cell.get("vertex")

        if not vertex or not value or "swimlane" in style:
            continue
        if cid in ("0", "1"):
            continue
        if not id_to_container.get(cid, False) and "<b>" not in value and "<div>" not in value:
            continue

        topic_id = resolve_topic(cid)
        if topic_id is None:
            continue

        book = parse_book_label(value)
        if not book["title"]:
            continue

        cat = _infer_category(style)
        books[topic_id].append({
            "title":    book["title"],
            "author":   book["author"],
            "category": cat,
        })

    return books


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
