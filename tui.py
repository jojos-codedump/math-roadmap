"""
tui.py
------
Curses-based interactive TUI for the Mathematics Roadmap Pathfinder.

Controls:
  ↑/↓       Navigate topic list
  /         Start search/filter
  ESC       Clear search
  ENTER     Select topic (start → then add to ends)
  BACKSPACE Remove last end target
  TAB       Switch between Start / Add-End focus
  m         Cycle mode (auto / multi / greedy)
  r / F5    Run pathfinder
  q / ESC   Quit (on main screen)
"""

import curses
import curses.textpad
import time
import sys
import os
import textwrap

# ── bring in our modules ─────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from parser import parse_drawio, get_topic_nodes, get_topic_edges
from graph_builder import build_graph, list_all_topics
from pathfinder import shortest_path, multi_endpoint_roadmap, greedy_multi_target


# ─────────────────────────────────────────────────────────────────
# Color pair indices
# ─────────────────────────────────────────────────────────────────
C_NORMAL      = 1   # white on dark
C_HEADER      = 2   # black on blue
C_FOOTER      = 3   # black on white
C_ESSENTIAL   = 4   # bright blue
C_OPT_REC     = 5   # bright magenta
C_OPTIONAL    = 6   # bright yellow
C_SELECTED    = 7   # black on cyan
C_HIGHLIGHT   = 8   # black on bright yellow (search match)
C_START_TAG   = 9   # black on green
C_END_TAG     = 10  # black on magenta
C_RESULT_STEP = 11  # bright cyan on dark
C_SHARED      = 12  # bright green
C_GOAL        = 13  # bright red (goal node)
C_BORDER      = 14  # dim white
C_TITLE       = 15  # bold white
C_MODE        = 16  # black on yellow
C_DIM         = 17  # dark grey
C_SUCCESS     = 18  # bright green
C_ERROR       = 19  # bright red


CATEGORY_COLOR = {
    "essential":            C_ESSENTIAL,
    "optional_recommended": C_OPT_REC,
    "optional":             C_OPTIONAL,
    "unknown":              C_NORMAL,
}

CATEGORY_GLYPH = {
    "essential":            "■",
    "optional_recommended": "◆",
    "optional":             "▲",
    "unknown":              "·",
}

MODE_NAMES = ["auto", "multi", "greedy"]
MODE_DESC = {
    "auto":   "Auto (single→1 target, multi→many)",
    "multi":  "Merged curriculum (all targets)",
    "greedy": "Greedy nearest-neighbour order",
}


# ─────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────

def safe_addstr(win, y, x, text, attr=0):
    """Add string safely, clipping to window bounds."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    max_len = w - x - 1
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, text[:max_len], attr)
    except curses.error:
        pass


def draw_box(win, y, x, h, w, title="", color=C_BORDER):
    """Draw a box with optional title."""
    attr = curses.color_pair(color)
    H, W = win.getmaxyx()

    # Clamp
    if y + h > H: h = H - y
    if x + w > W: w = W - x
    if h < 2 or w < 2: return

    try:
        win.attron(attr)
        # Top
        win.addch(y,       x,       curses.ACS_ULCORNER)
        win.hline(y,       x + 1,   curses.ACS_HLINE, w - 2)
        win.addch(y,       x + w - 1, curses.ACS_URCORNER)
        # Sides
        win.vline(y + 1,   x,       curses.ACS_VLINE, h - 2)
        win.vline(y + 1,   x + w - 1, curses.ACS_VLINE, h - 2)
        # Bottom
        win.addch(y + h - 1, x,     curses.ACS_LLCORNER)
        win.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        win.attroff(attr)
    except curses.error:
        pass

    if title:
        t = f" {title} "
        tx = x + max(2, (w - len(t)) // 2)
        safe_addstr(win, y, tx, t, curses.color_pair(C_TITLE) | curses.A_BOLD)


def fill_rect(win, y, x, h, w, char=" ", attr=0):
    for row in range(y, y + h):
        safe_addstr(win, row, x, char * w, attr)


# ─────────────────────────────────────────────────────────────────
# Main TUI App
# ─────────────────────────────────────────────────────────────────

class MathRoadmapTUI:

    def __init__(self, stdscr, drawio_path: str):
        self.scr = stdscr
        self.drawio_path = drawio_path

        # State
        self.topics      = []           # [{id, label, category, in_degree, out_degree}]
        self.G           = None
        self.filter_str  = ""
        self.filtered    = []           # indices into self.topics
        self.cursor      = 0            # position in filtered list
        self.scroll      = 0            # scroll offset in filtered list

        self.start_id    = None
        self.end_ids     = []           # list of node IDs
        self.mode_idx    = 0            # index into MODE_NAMES
        self.focus       = "start"      # "start" | "end"

        self.result      = None         # last pathfinder result dict
        self.result_mode = None         # "single"|"multi"|"greedy"
        self.result_scroll = 0
        self.status_msg  = ""
        self.status_ok   = True

        self.searching   = False
        self.search_buf  = ""

        self.running = True

    # ─── init ────────────────────────────────────────────────────

    def setup_colors(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(C_NORMAL,      curses.COLOR_WHITE,   -1)
        curses.init_pair(C_HEADER,      curses.COLOR_BLACK,   curses.COLOR_BLUE)
        curses.init_pair(C_FOOTER,      curses.COLOR_BLACK,   curses.COLOR_WHITE)
        curses.init_pair(C_ESSENTIAL,   curses.COLOR_CYAN,    -1)
        curses.init_pair(C_OPT_REC,     curses.COLOR_MAGENTA, -1)
        curses.init_pair(C_OPTIONAL,    curses.COLOR_YELLOW,  -1)
        curses.init_pair(C_SELECTED,    curses.COLOR_BLACK,   curses.COLOR_CYAN)
        curses.init_pair(C_HIGHLIGHT,   curses.COLOR_BLACK,   curses.COLOR_YELLOW)
        curses.init_pair(C_START_TAG,   curses.COLOR_BLACK,   curses.COLOR_GREEN)
        curses.init_pair(C_END_TAG,     curses.COLOR_BLACK,   curses.COLOR_MAGENTA)
        curses.init_pair(C_RESULT_STEP, curses.COLOR_CYAN,    -1)
        curses.init_pair(C_SHARED,      curses.COLOR_GREEN,   -1)
        curses.init_pair(C_GOAL,        curses.COLOR_RED,     -1)
        curses.init_pair(C_BORDER,      curses.COLOR_WHITE,   -1)
        curses.init_pair(C_TITLE,       curses.COLOR_WHITE,   -1)
        curses.init_pair(C_MODE,        curses.COLOR_BLACK,   curses.COLOR_YELLOW)
        curses.init_pair(C_DIM,         curses.COLOR_BLACK,   -1)
        curses.init_pair(C_SUCCESS,     curses.COLOR_GREEN,   -1)
        curses.init_pair(C_ERROR,       curses.COLOR_RED,     -1)

    def load_graph(self):
        self.set_status("Loading roadmap…", ok=True)
        self.scr.refresh()
        parsed      = parse_drawio(self.drawio_path)
        tnodes      = get_topic_nodes(parsed)
        tedges      = get_topic_edges(parsed, set(tnodes.keys()))
        self.G      = build_graph(tnodes, tedges)
        self.topics = list_all_topics(self.G)
        self.apply_filter()
        self.set_status(
            f"Loaded {self.G.number_of_nodes()} topics, {self.G.number_of_edges()} connections.",
            ok=True
        )

    # ─── filter ──────────────────────────────────────────────────

    def apply_filter(self):
        q = self.filter_str.lower()
        if not q:
            self.filtered = list(range(len(self.topics)))
        else:
            self.filtered = [
                i for i, t in enumerate(self.topics)
                if q in t["label"].lower()
            ]
        self.cursor = min(self.cursor, max(0, len(self.filtered) - 1))
        self.scroll  = 0

    def current_topic(self):
        if not self.filtered:
            return None
        idx = self.filtered[self.cursor]
        return self.topics[idx]

    # ─── status ──────────────────────────────────────────────────

    def set_status(self, msg: str, ok: bool = True):
        self.status_msg = msg
        self.status_ok  = ok

    # ─── layout helpers ──────────────────────────────────────────

    def dimensions(self):
        H, W = self.scr.getmaxyx()
        list_w   = min(48, W // 2)
        result_w = W - list_w
        return H, W, list_w, result_w

    # ─── drawing ─────────────────────────────────────────────────

    def draw_header(self):
        H, W, lw, rw = self.dimensions()
        attr = curses.color_pair(C_HEADER) | curses.A_BOLD
        fill_rect(self.scr, 0, 0, 1, W, " ", attr)
        title = "  ∑  MATHEMATICS ROADMAP  ─  PATHFINDER"
        safe_addstr(self.scr, 0, 0, title, attr)

        mode = MODE_NAMES[self.mode_idx]
        mode_str = f"  MODE: {mode.upper()}  "
        safe_addstr(self.scr, 0, W - len(mode_str) - 1,
                    mode_str, curses.color_pair(C_MODE) | curses.A_BOLD)

    def draw_footer(self):
        H, W, lw, rw = self.dimensions()
        attr = curses.color_pair(C_FOOTER)
        fill_rect(self.scr, H - 1, 0, 1, W, " ", attr)

        if self.searching:
            hint = f"  SEARCH: {self.search_buf}_   [ENTER] confirm   [ESC] cancel"
        else:
            hint = (
                "  [↑↓] navigate   [/] search   [ENTER] select   "
                "[TAB] start↔end   [m] mode   [r] run   [q] quit"
            )
        safe_addstr(self.scr, H - 1, 0, hint[:W - 1], attr)

        # Status message on right side of footer
        if self.status_msg:
            s_attr = curses.color_pair(C_SUCCESS) if self.status_ok else curses.color_pair(C_ERROR)
            s_attr |= curses.A_BOLD
            msg = self.status_msg[:W // 2]
            safe_addstr(self.scr, H - 1, W - len(msg) - 2, msg, s_attr | curses.color_pair(C_FOOTER))

    def draw_selection_bar(self):
        H, W, lw, rw = self.dimensions()
        y = H - 4
        fill_rect(self.scr, y, 0, 3, W, " ", curses.color_pair(C_NORMAL))
        draw_box(self.scr, y, 0, 3, W, color=C_BORDER)

        # Start label
        start_label = self.G.nodes[self.start_id]["label"] if self.start_id else "─ not set ─"
        s_attr = curses.color_pair(C_START_TAG) | curses.A_BOLD if self.start_id else curses.color_pair(C_DIM)
        safe_addstr(self.scr, y + 1, 2,  "START ▶ ", curses.color_pair(C_NORMAL) | curses.A_BOLD)
        safe_addstr(self.scr, y + 1, 10, start_label[:lw - 12], s_attr)

        # Separator
        safe_addstr(self.scr, y + 1, lw, "│", curses.color_pair(C_BORDER))

        # End labels
        if self.end_ids:
            end_labels = [self.G.nodes[eid]["label"] for eid in self.end_ids]
            end_str = "  ·  ".join(end_labels)
        else:
            end_str = "─ not set ─"
        e_attr = curses.color_pair(C_END_TAG) | curses.A_BOLD if self.end_ids else curses.color_pair(C_DIM)
        safe_addstr(self.scr, y + 1, lw + 2,  "END(S) ▶ ", curses.color_pair(C_NORMAL) | curses.A_BOLD)
        safe_addstr(self.scr, y + 1, lw + 11, end_str[:W - lw - 13], e_attr)

        # Focus indicator
        if self.focus == "start":
            safe_addstr(self.scr, y, 2, "[ setting START ]", curses.color_pair(C_START_TAG) | curses.A_BOLD)
        else:
            safe_addstr(self.scr, y, lw + 2, "[ adding ENDS ]", curses.color_pair(C_END_TAG) | curses.A_BOLD)
            safe_addstr(self.scr, y + 1, W - 22,
                        "[BKSP] remove last end", curses.color_pair(C_DIM))

    def draw_topic_list(self):
        H, W, lw, rw = self.dimensions()
        list_h = H - 6   # below header (1) above selection bar (3) above footer (1) + 1
        list_top = 1

        draw_box(self.scr, list_top, 0, list_h, lw, title="TOPICS", color=C_BORDER)

        # Filter indicator
        if self.filter_str:
            finfo = f" filter: {self.filter_str} ({len(self.filtered)}) "
            safe_addstr(self.scr, list_top, lw - len(finfo) - 2,
                        finfo, curses.color_pair(C_HIGHLIGHT) | curses.A_BOLD)

        inner_h = list_h - 2
        inner_w = lw - 4

        # Adjust scroll to keep cursor visible
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        if self.cursor >= self.scroll + inner_h:
            self.scroll = self.cursor - inner_h + 1

        visible = self.filtered[self.scroll: self.scroll + inner_h]

        for row, idx in enumerate(visible):
            t = self.topics[idx]
            ry = list_top + 1 + row
            cat = t["category"]
            glyph = CATEGORY_GLYPH.get(cat, "·")
            label = t["label"]

            # Background attr
            is_cursor  = (self.scroll + row) == self.cursor
            is_start   = t["id"] == self.start_id
            is_end     = t["id"] in self.end_ids

            if is_cursor:
                bg_attr = curses.color_pair(C_SELECTED) | curses.A_BOLD
            else:
                bg_attr = curses.color_pair(C_NORMAL)

            # Fill row background
            safe_addstr(self.scr, ry, 2, " " * inner_w, bg_attr)

            # Glyph
            glyph_attr = curses.color_pair(CATEGORY_COLOR.get(cat, C_NORMAL)) | curses.A_BOLD
            if is_cursor:
                glyph_attr = bg_attr
            safe_addstr(self.scr, ry, 2, glyph, glyph_attr)

            # Tags
            x_off = 4
            if is_start:
                tag = " S "
                safe_addstr(self.scr, ry, x_off,
                            tag, curses.color_pair(C_START_TAG) | curses.A_BOLD)
                x_off += len(tag) + 1
            elif is_end:
                pos = self.end_ids.index(t["id"]) + 1
                tag = f" E{pos} "
                safe_addstr(self.scr, ry, x_off,
                            tag, curses.color_pair(C_END_TAG) | curses.A_BOLD)
                x_off += len(tag) + 1

            # Label
            max_label = inner_w - x_off + 2
            lbl = label[:max_label]
            # Highlight search match
            if self.filter_str and not is_cursor:
                q = self.filter_str.lower()
                lo = lbl.lower()
                match_start = lo.find(q)
                if match_start >= 0:
                    safe_addstr(self.scr, ry, x_off, lbl[:match_start], bg_attr)
                    safe_addstr(self.scr, ry, x_off + match_start,
                                lbl[match_start:match_start + len(q)],
                                curses.color_pair(C_HIGHLIGHT) | curses.A_BOLD)
                    safe_addstr(self.scr, ry, x_off + match_start + len(q),
                                lbl[match_start + len(q):], bg_attr)
                else:
                    safe_addstr(self.scr, ry, x_off, lbl, bg_attr)
            else:
                safe_addstr(self.scr, ry, x_off, lbl, bg_attr)

        # Scrollbar
        if len(self.filtered) > inner_h:
            sb_h = max(1, inner_h * inner_h // len(self.filtered))
            sb_y = self.scroll * (inner_h - sb_h) // max(1, len(self.filtered) - inner_h)
            for row in range(inner_h):
                ch = "█" if sb_y <= row < sb_y + sb_h else "░"
                safe_addstr(self.scr, list_top + 1 + row, lw - 2,
                            ch, curses.color_pair(C_DIM))

    def draw_result_panel(self):
        H, W, lw, rw = self.dimensions()
        panel_h = H - 6
        panel_top = 1
        px = lw
        pw = rw

        draw_box(self.scr, panel_top, px, panel_h, pw, title="ROADMAP", color=C_BORDER)

        if not self.result:
            # Splash / instructions
            lines = [
                "",
                "  Welcome to Mathematics Roadmap Pathfinder",
                "",
                "  ─────────────────────────────────────────",
                "",
                "  HOW TO USE:",
                "",
                "  1.  Use ↑ ↓ to browse topics on the left",
                "  2.  Press ENTER to set your START topic",
                "  3.  Press TAB to switch to END selection",
                "  4.  Press ENTER to add END topic(s)",
                "  5.  Press [m] to cycle the path mode",
                "  6.  Press [r] or F5 to compute your path",
                "",
                "  ─────────────────────────────────────────",
                "",
                "  MODES:",
                "    auto   → single if 1 target, multi if >1",
                "    multi  → merged curriculum (deduplicated)",
                "    greedy → nearest-neighbour goal ordering",
                "",
                "  ─────────────────────────────────────────",
                "",
                "  LEGEND:",
                "    ■  Essential topic",
                "    ◆  Optional but recommended",
                "    ▲  Optional",
                "    ★  Your goal (end node)",
                "    ◈  Shared prerequisite",
            ]
            for i, line in enumerate(lines):
                if i + panel_top + 1 >= panel_top + panel_h - 1:
                    break
                c = C_NORMAL
                if "HOW TO USE" in line or "MODES" in line or "LEGEND" in line:
                    c = C_TITLE
                    safe_addstr(self.scr, panel_top + 1 + i, px + 2,
                                line, curses.color_pair(c) | curses.A_BOLD)
                elif line.startswith("  ■"):
                    safe_addstr(self.scr, panel_top + 1 + i, px + 2,
                                "  ", curses.color_pair(C_NORMAL))
                    safe_addstr(self.scr, panel_top + 1 + i, px + 4,
                                "■", curses.color_pair(C_ESSENTIAL) | curses.A_BOLD)
                    safe_addstr(self.scr, panel_top + 1 + i, px + 6,
                                line[4:], curses.color_pair(C_NORMAL))
                elif line.startswith("  ◆"):
                    safe_addstr(self.scr, panel_top + 1 + i, px + 2,
                                "  ", curses.color_pair(C_NORMAL))
                    safe_addstr(self.scr, panel_top + 1 + i, px + 4,
                                "◆", curses.color_pair(C_OPT_REC) | curses.A_BOLD)
                    safe_addstr(self.scr, panel_top + 1 + i, px + 6,
                                line[4:], curses.color_pair(C_NORMAL))
                elif line.startswith("  ▲"):
                    safe_addstr(self.scr, panel_top + 1 + i, px + 2,
                                "  ", curses.color_pair(C_NORMAL))
                    safe_addstr(self.scr, panel_top + 1 + i, px + 4,
                                "▲", curses.color_pair(C_OPTIONAL) | curses.A_BOLD)
                    safe_addstr(self.scr, panel_top + 1 + i, px + 6,
                                line[4:], curses.color_pair(C_NORMAL))
                else:
                    safe_addstr(self.scr, panel_top + 1 + i, px + 2,
                                line, curses.color_pair(c))
            return

        # ── render result ────────────────────────────────────────
        inner_h = panel_h - 2
        inner_w = pw - 4
        lines = self._build_result_lines(inner_w)

        # Scroll
        max_scroll = max(0, len(lines) - inner_h)
        self.result_scroll = max(0, min(self.result_scroll, max_scroll))

        if max_scroll > 0:
            scroll_hint = f" ↑↓ scroll ({self.result_scroll + 1}/{len(lines)}) "
            safe_addstr(self.scr, panel_top + panel_h - 1,
                        px + pw - len(scroll_hint) - 2,
                        scroll_hint, curses.color_pair(C_DIM))

        visible = lines[self.result_scroll: self.result_scroll + inner_h]
        for row, (text, attr) in enumerate(visible):
            safe_addstr(self.scr, panel_top + 1 + row, px + 2, " " * inner_w,
                        curses.color_pair(C_NORMAL))
            safe_addstr(self.scr, panel_top + 1 + row, px + 2, text, attr)

    def _build_result_lines(self, width: int) -> list:
        """
        Build a list of (text, attr) tuples for the result panel.
        """
        G = self.G
        lines = []

        def label(nid):
            return G.nodes[nid].get("label", nid) if nid in G else nid

        def cat(nid):
            return G.nodes[nid].get("category", "unknown") if nid in G else "unknown"

        def add(text, attr=0):
            lines.append((text[:width], attr))

        def add_sep():
            add("─" * width, curses.color_pair(C_DIM))

        mode = self.result_mode
        r    = self.result

        if mode == "single":
            if not r["found"]:
                add("  ✗ No path found.", curses.color_pair(C_ERROR) | curses.A_BOLD)
                add(f"  {r['error']}", curses.color_pair(C_ERROR))
                return lines

            path = r["path"]
            add(f"  Steps: {len(path)}   Weight: {r['total_weight']}",
                curses.color_pair(C_SUCCESS) | curses.A_BOLD)
            add_sep()

            for i, nid in enumerate(path):
                lbl   = label(nid)
                c     = cat(nid)
                glyph = CATEGORY_GLYPH.get(c, "·")
                g_attr = curses.color_pair(CATEGORY_COLOR.get(c, C_NORMAL)) | curses.A_BOLD

                is_last = i == len(path) - 1
                conn  = "└──" if is_last else "├──"
                step  = f"  {i+1:>2}  {conn} "

                # Write step prefix
                lines.append((step + glyph + "  " + lbl, curses.color_pair(C_NORMAL)))
                # Rewrite glyph with color
                # We'll encode as tuple (prefix, glyph, suffix, cat)
                lines[-1] = ("__STEP__", {"step": step, "glyph": glyph,
                                          "label": lbl, "cat": c,
                                          "is_goal": is_last, "is_shared": False})
                if not is_last:
                    add(f"  {'':>2}  │", curses.color_pair(C_DIM))

        elif mode == "multi":
            merged  = r.get("merged_nodes", [])
            shared  = r.get("shared_nodes", set())
            targets = r.get("target_nodes", set())
            errors  = r.get("errors", [])

            if errors:
                for err in errors:
                    add(f"  ⚠  {err}", curses.color_pair(C_ERROR))
                add_sep()

            add(f"  Unique steps: {len(merged)}   Shared nodes: {len(shared)}",
                curses.color_pair(C_SUCCESS) | curses.A_BOLD)
            add_sep()

            for i, nid in enumerate(merged):
                lbl   = label(nid)
                c     = cat(nid)
                glyph = CATEGORY_GLYPH.get(c, "·")
                is_goal   = nid in targets
                is_shared = nid in shared and not is_goal
                is_last   = i == len(merged) - 1
                conn  = "└──" if is_last else "├──"
                step  = f"  {i+1:>2}  {conn} "
                lines.append(("__STEP__", {"step": step, "glyph": glyph,
                                           "label": lbl, "cat": c,
                                           "is_goal": is_goal,
                                           "is_shared": is_shared}))
                if not is_last:
                    add(f"  {'':>2}  │", curses.color_pair(C_DIM))

            add_sep()
            for tid, pr in r.get("individual_paths", {}).items():
                tl = label(tid)
                if pr["found"]:
                    add(f"  ✓  {tl}  ({len(pr['path'])} steps)",
                        curses.color_pair(C_SUCCESS) | curses.A_BOLD)
                else:
                    add(f"  ✗  {tl}",
                        curses.color_pair(C_ERROR))

        elif mode == "greedy":
            segments = r.get("segments", [])
            errors   = r.get("errors", [])

            if errors:
                for err in errors:
                    add(f"  ⚠  {err}", curses.color_pair(C_ERROR))

            add(f"  Goals: {len(segments)}   Total weight: {r.get('total_weight', 0)}",
                curses.color_pair(C_SUCCESS) | curses.A_BOLD)
            step = 1
            for seg in segments:
                add_sep()
                fl = label(seg["from"])
                tl = label(seg["to"])
                add(f"  ── {fl}  →  {tl}  (w:{seg['weight']})",
                    curses.color_pair(C_OPT_REC) | curses.A_BOLD)
                add("")
                for nid in seg["path"]:
                    lbl  = label(nid)
                    c    = cat(nid)
                    glyph = CATEGORY_GLYPH.get(c, "·")
                    is_goal = nid == seg["to"]
                    lines.append(("__STEP__", {"step": f"  {step:>2}  ──▶ ",
                                               "glyph": glyph, "label": lbl,
                                               "cat": c, "is_goal": is_goal,
                                               "is_shared": False}))
                    step += 1

        # ── Expand __STEP__ entries ──────────────────────────────
        # (we stored them as dicts; now convert to (text, attr) rendering
        #  in a second pass so we can do multi-attr per line in the renderer)
        expanded = []
        for text, attr in lines:
            if text == "__STEP__":
                d      = attr   # it's actually a dict
                # We'll render these as tagged tuples:
                expanded.append(("__RENDER_STEP__", d))
            else:
                expanded.append((text, attr))
        return expanded

    def _render_result_line(self, win, y, x, width, entry):
        """Render a single result line that may be a tagged step dict."""
        text, attr = entry
        if text != "__RENDER_STEP__":
            safe_addstr(win, y, x, " " * width, curses.color_pair(C_NORMAL))
            safe_addstr(win, y, x, text[:width], attr)
            return

        d      = attr
        step   = d["step"]
        glyph  = d["glyph"]
        lbl    = d["label"]
        c      = d["cat"]
        is_goal   = d["is_goal"]
        is_shared = d["is_shared"]

        safe_addstr(win, y, x, " " * width, curses.color_pair(C_NORMAL))
        cx = x
        safe_addstr(win, y, cx, step, curses.color_pair(C_DIM))
        cx += len(step)
        g_attr = curses.color_pair(CATEGORY_COLOR.get(c, C_NORMAL)) | curses.A_BOLD
        safe_addstr(win, y, cx, glyph, g_attr)
        cx += 2
        if is_goal:
            tag = " ★ "
            safe_addstr(win, y, cx, tag, curses.color_pair(C_GOAL) | curses.A_BOLD)
            cx += len(tag)
        elif is_shared:
            tag = " ◈ "
            safe_addstr(win, y, cx, tag, curses.color_pair(C_SHARED) | curses.A_BOLD)
            cx += len(tag)
        safe_addstr(win, y, cx, lbl[:x + width - cx], curses.color_pair(C_NORMAL))

    def draw_result_panel_rich(self):
        """Full result panel renderer that handles __RENDER_STEP__ entries."""
        H, W, lw, rw = self.dimensions()
        panel_h  = H - 6
        panel_top = 1
        px = lw
        pw = rw

        draw_box(self.scr, panel_top, px, panel_h, pw, title="ROADMAP", color=C_BORDER)

        if not self.result:
            self.draw_result_panel()
            return

        inner_h = panel_h - 2
        inner_w = pw - 4
        lines = self._build_result_lines(inner_w)

        max_scroll = max(0, len(lines) - inner_h)
        self.result_scroll = max(0, min(self.result_scroll, max_scroll))

        if max_scroll > 0:
            scroll_hint = f" ↑↓ scroll ({self.result_scroll + 1}/{len(lines)}) "
            safe_addstr(self.scr, panel_top + panel_h - 1,
                        px + pw - len(scroll_hint) - 2,
                        scroll_hint, curses.color_pair(C_DIM))

        visible = lines[self.result_scroll: self.result_scroll + inner_h]
        for row, entry in enumerate(visible):
            ry = panel_top + 1 + row
            text, attr = entry
            if text == "__RENDER_STEP__":
                self._render_result_line(self.scr, ry, px + 2, inner_w, entry)
            else:
                safe_addstr(self.scr, ry, px + 2, " " * inner_w, curses.color_pair(C_NORMAL))
                safe_addstr(self.scr, ry, px + 2, text[:inner_w], attr)

    def draw_all(self):
        self.scr.erase()
        self.draw_header()
        self.draw_topic_list()
        self.draw_result_panel_rich()
        self.draw_selection_bar()
        self.draw_footer()
        self.scr.refresh()

    # ─── run pathfinder ──────────────────────────────────────────

    def run_pathfinder(self):
        if not self.start_id:
            self.set_status("Please select a START topic first.", ok=False)
            return
        if not self.end_ids:
            self.set_status("Please select at least one END topic.", ok=False)
            return

        mode = MODE_NAMES[self.mode_idx]
        if mode == "auto":
            mode = "single" if len(self.end_ids) == 1 else "multi"

        self.set_status("Computing path…", ok=True)
        self.draw_all()

        try:
            if mode == "single":
                self.result = shortest_path(self.G, self.start_id, self.end_ids[0])
            elif mode == "multi":
                self.result = multi_endpoint_roadmap(self.G, self.start_id, self.end_ids)
            elif mode == "greedy":
                self.result = greedy_multi_target(self.G, self.start_id, self.end_ids)

            self.result_mode  = mode
            self.result_scroll = 0

            if mode == "single":
                ok = self.result.get("found", False)
            else:
                ok = self.result.get("all_found", False)

            if ok:
                self.set_status("Path found! Use ↑↓ in the right panel to scroll.", ok=True)
            else:
                self.set_status("Partial result — some paths not found.", ok=False)

        except Exception as e:
            self.set_status(f"Error: {e}", ok=False)

    # ─── input handling ──────────────────────────────────────────

    def handle_key(self, key):
        H, W, lw, rw = self.dimensions()
        list_h = H - 6
        inner_h = list_h - 2

        # ── Search mode ──────────────────────────────────────────
        if self.searching:
            if key == 27:                   # ESC
                self.searching   = False
                self.search_buf  = ""
                self.filter_str  = ""
                self.apply_filter()
            elif key in (10, 13, curses.KEY_ENTER):
                self.searching  = False
                self.filter_str = self.search_buf
                self.apply_filter()
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self.search_buf = self.search_buf[:-1]
                self.filter_str = self.search_buf
                self.apply_filter()
            elif 32 <= key <= 126:
                self.search_buf += chr(key)
                self.filter_str  = self.search_buf
                self.apply_filter()
            return

        # ── Normal mode ──────────────────────────────────────────
        if key in (ord('q'), ord('Q')):
            self.running = False

        elif key == ord('/'):
            self.searching  = True
            self.search_buf = self.filter_str

        elif key == 27:                     # ESC — clear search
            self.filter_str = ""
            self.search_buf = ""
            self.apply_filter()

        elif key == curses.KEY_UP:
            if self.result and self.result_scroll > 0:
                # If we have results and user might want to scroll them
                # Pressing UP scrolls the topic list
                pass
            self.cursor = max(0, self.cursor - 1)
            # Scroll result panel if cursor is at top of list
            if self.result and self.cursor == 0:
                self.result_scroll = max(0, self.result_scroll - 1)

        elif key == curses.KEY_DOWN:
            self.cursor = min(len(self.filtered) - 1, self.cursor + 1)

        elif key == curses.KEY_PPAGE:       # Page Up
            self.cursor = max(0, self.cursor - inner_h)

        elif key == curses.KEY_NPAGE:       # Page Down
            self.cursor = min(len(self.filtered) - 1, self.cursor + inner_h)

        elif key == curses.KEY_HOME:
            self.cursor = 0
            self.scroll  = 0

        elif key == curses.KEY_END:
            self.cursor = max(0, len(self.filtered) - 1)

        elif key in (9,):                   # TAB — toggle focus
            self.focus = "end" if self.focus == "start" else "start"
            self.set_status(
                f"Focus: {'selecting START' if self.focus == 'start' else 'adding END topics'}",
                ok=True
            )

        elif key in (10, 13, curses.KEY_ENTER):
            t = self.current_topic()
            if t:
                if self.focus == "start":
                    self.start_id = t["id"]
                    self.set_status(f"Start set: {t['label']}", ok=True)
                    self.focus = "end"       # auto-advance to end selection
                else:
                    if t["id"] == self.start_id:
                        self.set_status("Cannot use START as END.", ok=False)
                    elif t["id"] in self.end_ids:
                        self.set_status(f"Already in end list: {t['label']}", ok=False)
                    else:
                        self.end_ids.append(t["id"])
                        self.set_status(f"End added: {t['label']}  ({len(self.end_ids)} total)", ok=True)

        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if self.focus == "end" and self.end_ids:
                removed = self.G.nodes[self.end_ids.pop()]["label"]
                self.set_status(f"Removed end: {removed}", ok=True)

        elif key in (ord('m'), ord('M')):
            self.mode_idx = (self.mode_idx + 1) % len(MODE_NAMES)
            mode = MODE_NAMES[self.mode_idx]
            self.set_status(f"Mode: {MODE_DESC[mode]}", ok=True)

        elif key in (ord('r'), ord('R'), curses.KEY_F5):
            self.run_pathfinder()

        elif key == curses.KEY_SR:          # Shift+Up → scroll result
            self.result_scroll = max(0, self.result_scroll - 1)

        elif key == curses.KEY_SF:          # Shift+Down → scroll result
            self.result_scroll += 1

        elif key in (ord('+'), ord('=')):   # scroll result down
            self.result_scroll += 1

        elif key == ord('-'):               # scroll result up
            self.result_scroll = max(0, self.result_scroll - 1)

    # ─── main loop ───────────────────────────────────────────────

    def run(self):
        self.setup_colors()
        curses.curs_set(0)
        self.scr.nodelay(False)
        self.scr.keypad(True)
        self.scr.timeout(100)

        self.load_graph()

        while self.running:
            self.draw_all()
            key = self.scr.getch()
            if key != -1:
                self.handle_key(key)


# ─────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────

def main(stdscr, drawio_path: str):
    app = MathRoadmapTUI(stdscr, drawio_path)
    app.run()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Math Roadmap TUI")
    p.add_argument("--file", "-f", default="mathematics-roadmap.drawio",
                   help="Path to .drawio file")
    args = p.parse_args()

    if not os.path.exists(args.file):
        print(f"Error: file not found: {args.file}")
        sys.exit(1)

    curses.wrapper(main, args.file)
