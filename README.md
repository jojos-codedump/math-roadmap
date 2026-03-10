# 🧮 Mathematics Roadmap Pathfinder

A shortest-path traversal tool for the Mathematics Learning Roadmap (`.drawio` format).
Includes both an interactive **curses TUI** (`tui.py`) and a **CLI** (`main.py`).

---

## Credits

The roadmap data used by this tool — the topic graph, prerequisites, and learning path structure — is based entirely on the original work by **Talal Alrawajfeh**:

> **Mathematics Roadmap**
> [github.com/TalalAlrawajfeh/mathematics-roadmap](https://github.com/TalalAlrawajfeh/mathematics-roadmap/blob/master/mathematics-roadmap.jpg)

All credit for the intellectual curation of topics, their ordering, and the recommended resources goes to the original author. This project only adds a programmatic traversal layer on top of that work.

---

## Setup

```bash
pip install networkx
```

Python 3.10+ required (uses `str | None` union syntax).

---

## Interactive TUI (Recommended)

```bash
python tui.py --file mathematics-roadmap.drawio
```

### TUI Controls

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate topic list |
| `/` | Search / filter topics |
| `ESC` | Clear search |
| `ENTER` | Select topic (as start, then as end) |
| `TAB` | Toggle focus: setting START ↔ adding ENDs |
| `BACKSPACE` | Remove last end target |
| `m` | Cycle mode (auto → multi → greedy) |
| `r` / `F5` | Run pathfinder |
| `+` / `-` | Scroll result panel |
| `q` | Quit |

---

## CLI Usage

### 1. List all available topics
```bash
python main.py --file mathematics-roadmap.drawio --list
```

### 2. Single endpoint — shortest path from A to B
```bash
python main.py --file mathematics-roadmap.drawio \
  --start "Calculus" \
  --end "Real Analysis"
```

### 3. Multiple endpoints — merged curriculum (visits ALL goals)
```bash
python main.py --file mathematics-roadmap.drawio \
  --start "Calculus" \
  --end "Real Analysis" "Algebraic Topology" "Complex Analysis"
```

### 4. Multiple endpoints — greedy ordered visit (nearest goal first)
```bash
python main.py --file mathematics-roadmap.drawio \
  --start "Calculus" \
  --end "Real Analysis" "Algebraic Topology" \
  --mode greedy
```

### 5. Export result to JSON
```bash
python main.py --file mathematics-roadmap.drawio \
  --start "Calculus" \
  --end "Real Analysis" \
  --export result.json
```

---

## Modes

| Mode      | Description |
|-----------|-------------|
| `auto`    | Picks `single` if 1 target, `multi` if >1 (default) |
| `single`  | Dijkstra → one target |
| `multi`   | Merged curriculum reaching all targets; shared prerequisites appear once |
| `greedy`  | Nearest-neighbour: from current position, always visit closest unvisited target next |

---

## Node Categories (from roadmap legend)

| Colour | Category | Weight |
|--------|----------|--------|
| 🔵 Blue (`#dae8fc`) | Essential | 1 |
| 🟣 Purple (`#e1d5e7`) | Optional but Recommended | 2 |
| 🟡 Yellow (`#fff2cc`) | Optional | 3 |

Edge weights mirror the category of the connection — lower weight = higher priority in Dijkstra.

---

## File Structure

```
math-roadmap-pathfinder/
├── tui.py            ← ✨ Interactive curses TUI (start here)
├── main.py           ← CLI entrypoint
├── parser.py         ← .drawio XML parser
├── graph_builder.py  ← NetworkX graph construction
├── pathfinder.py     ← Dijkstra / multi-endpoint algorithms
├── output.py         ← Formatted display + JSON export
└── README.md         ← This file
```

---

## How It Works

1. **`parser.py`** reads the `.drawio` XML, extracts all `mxCell` nodes and edges, strips HTML from labels, and resolves child cells back to their parent swimlane containers.

2. **`graph_builder.py`** builds a `networkx.DiGraph` where:
   - Each node = a topic (e.g. "Calculus", "Real Analysis")
   - Each edge = a directed dependency with a weight based on category

3. **`pathfinder.py`** runs:
   - **Dijkstra** for single shortest path
   - **Merge + Topological Sort** for multi-endpoint merged curriculum
   - **Greedy Nearest-Neighbour** for ordered goal traversal

4. **`output.py`** formats results as readable terminal roadmaps and optionally exports to JSON.