"""
tui.py
------
Curses-based interactive TUI for the Mathematics Roadmap Pathfinder.

Controls:
  ↑/↓       Navigate topic list
  /         Start search/filter
  ESC       Clear search / clear result
  ENTER     Select topic (start → then add to ends)
  BACKSPACE Remove last end target
  TAB       Switch between Start / Add-End focus
  m         Cycle mode (auto / multi / greedy)
  r / F5    Run pathfinder
  + / -     Scroll right panel
  q         Quit
"""

import curses
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from parser import parse_drawio, get_topic_nodes, get_topic_edges, get_topic_books_rich
from graph_builder import build_graph, list_all_topics
from pathfinder import shortest_path, multi_endpoint_roadmap, greedy_multi_target
from output import CATEGORY_LABELS

# ─────────────────────────────────────────────────────────────────
# Color pair indices
# ─────────────────────────────────────────────────────────────────
C_NORMAL      = 1
C_HEADER      = 2
C_FOOTER      = 3
C_ESSENTIAL   = 4
C_OPT_REC     = 5
C_OPTIONAL    = 6
C_SELECTED    = 7
C_HIGHLIGHT   = 8
C_START_TAG   = 9
C_END_TAG     = 10
C_SHARED      = 12
C_GOAL        = 13
C_BORDER      = 14
C_TITLE       = 15
C_MODE        = 16
C_DIM         = 17
C_SUCCESS     = 18
C_ERROR       = 19
C_BOOK_TITLE  = 20
C_BOOK_AUTHOR = 21
C_SECTION_HDR = 22

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
BOOK_GLYPH = {
    "essential":            "[E]",
    "optional_recommended": "[R]",
    "optional":             "[O]",
    "unknown":              "[?]",
}
MODE_NAMES = ["auto", "multi", "greedy"]
MODE_DESC = {
    "auto":   "Auto (single→1 target, multi→many)",
    "multi":  "Merged curriculum (all targets)",
    "greedy": "Greedy nearest-neighbour order",
}


# ─────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────

def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    avail = w - x - 1
    if avail <= 0:
        return
    try:
        win.addstr(y, x, text[:avail], attr)
    except curses.error:
        pass


def draw_box(win, y, x, h, w, title="", color=C_BORDER):
    attr = curses.color_pair(color)
    H, W = win.getmaxyx()
    if y + h > H: h = H - y
    if x + w > W: w = W - x
    if h < 2 or w < 2:
        return
    try:
        win.attron(attr)
        win.addch(y,         x,         curses.ACS_ULCORNER)
        win.hline(y,         x + 1,     curses.ACS_HLINE, w - 2)
        win.addch(y,         x + w - 1, curses.ACS_URCORNER)
        win.vline(y + 1,     x,         curses.ACS_VLINE, h - 2)
        win.vline(y + 1,     x + w - 1, curses.ACS_VLINE, h - 2)
        win.addch(y + h - 1, x,         curses.ACS_LLCORNER)
        win.hline(y + h - 1, x + 1,     curses.ACS_HLINE, w - 2)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        win.attroff(attr)
    except curses.error:
        pass
    if title:
        t  = f" {title} "
        tx = x + max(2, (w - len(t)) // 2)
        safe_addstr(win, y, tx, t,
                    curses.color_pair(C_TITLE) | curses.A_BOLD)


def fill_rect(win, y, x, h, w, char=" ", attr=0):
    for row in range(y, y + h):
        safe_addstr(win, row, x, char * w, attr)


# ─────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────

class MathRoadmapTUI:

    def __init__(self, stdscr, drawio_path):
        self.scr         = stdscr
        self.drawio_path = drawio_path

        self.topics      = []
        self.G           = None
        self.books       = {}

        self.filter_str  = ""
        self.filtered    = []
        self.cursor      = 0
        self.scroll      = 0

        self.start_id    = None
        self.end_ids     = []
        self.mode_idx    = 0
        self.focus       = "start"

        self.result       = None
        self.result_mode  = None
        self.result_scroll = 0

        self.status_msg  = ""
        self.status_ok   = True
        self.searching   = False
        self.search_buf  = ""
        self.running     = True

    # ── init ─────────────────────────────────────────────────────

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
        curses.init_pair(C_SHARED,      curses.COLOR_GREEN,   -1)
        curses.init_pair(C_GOAL,        curses.COLOR_RED,     -1)
        curses.init_pair(C_BORDER,      curses.COLOR_WHITE,   -1)
        curses.init_pair(C_TITLE,       curses.COLOR_WHITE,   -1)
        curses.init_pair(C_MODE,        curses.COLOR_BLACK,   curses.COLOR_YELLOW)
        curses.init_pair(C_DIM,         8,                    -1)
        curses.init_pair(C_SUCCESS,     curses.COLOR_GREEN,   -1)
        curses.init_pair(C_ERROR,       curses.COLOR_RED,     -1)
        curses.init_pair(C_BOOK_TITLE,  curses.COLOR_WHITE,   -1)
        curses.init_pair(C_BOOK_AUTHOR, curses.COLOR_CYAN,    -1)
        curses.init_pair(C_SECTION_HDR, curses.COLOR_YELLOW,  -1)

    def load_graph(self):
        self.set_status("Loading roadmap…", ok=True)
        self.scr.refresh()
        parsed      = parse_drawio(self.drawio_path)
        tnodes      = get_topic_nodes(parsed)
        tedges      = get_topic_edges(parsed, set(tnodes.keys()))
        self.G      = build_graph(tnodes, tedges)
        self.topics = list_all_topics(self.G)
        self.books  = get_topic_books_rich(self.drawio_path, set(tnodes.keys()))
        self.apply_filter()
        self.set_status(
            f"Loaded {self.G.number_of_nodes()} topics · "
            f"{self.G.number_of_edges()} connections",
            ok=True,
        )

    # ── helpers ──────────────────────────────────────────────────

    def apply_filter(self):
        q = self.filter_str.lower()
        self.filtered = [
            i for i, t in enumerate(self.topics)
            if not q or q in t["label"].lower()
        ]
        self.cursor = min(self.cursor, max(0, len(self.filtered) - 1))
        self.scroll  = 0

    def current_topic(self):
        if not self.filtered:
            return None
        return self.topics[self.filtered[self.cursor]]

    def set_status(self, msg, ok=True):
        self.status_msg = msg
        self.status_ok  = ok

    def dimensions(self):
        H, W   = self.scr.getmaxyx()
        lw     = min(46, W // 2)
        rw     = W - lw
        return H, W, lw, rw

    # ── draw: header ─────────────────────────────────────────────

    def draw_header(self):
        H, W, lw, rw = self.dimensions()
        a = curses.color_pair(C_HEADER) | curses.A_BOLD
        fill_rect(self.scr, 0, 0, 1, W, " ", a)
        safe_addstr(self.scr, 0, 0,
                    "  ∑  MATHEMATICS ROADMAP  ─  PATHFINDER", a)
        ms = f"  MODE: {MODE_NAMES[self.mode_idx].upper()}  "
        safe_addstr(self.scr, 0, W - len(ms) - 1, ms,
                    curses.color_pair(C_MODE) | curses.A_BOLD)

    # ── draw: footer ─────────────────────────────────────────────

    def draw_footer(self):
        H, W, lw, rw = self.dimensions()
        a = curses.color_pair(C_FOOTER)
        fill_rect(self.scr, H - 1, 0, 1, W, " ", a)
        if self.searching:
            hint = f"  SEARCH: {self.search_buf}_   [ENTER] confirm   [ESC] cancel"
        else:
            hint = ("  [↑↓] nav   [/] search   [ENTER] select   "
                    "[TAB] start↔end   [m] mode   [r] run   [+/-] scroll   [q] quit")
        safe_addstr(self.scr, H - 1, 0, hint[:W - 1], a)
        if self.status_msg:
            sa = ((curses.color_pair(C_SUCCESS) if self.status_ok
                   else curses.color_pair(C_ERROR)) | curses.A_BOLD)
            msg = self.status_msg[:W // 2]
            safe_addstr(self.scr, H - 1, W - len(msg) - 2, msg, sa)

    # ── draw: selection bar ──────────────────────────────────────

    def draw_selection_bar(self):
        H, W, lw, rw = self.dimensions()
        y = H - 4
        fill_rect(self.scr, y, 0, 3, W, " ", curses.color_pair(C_NORMAL))
        draw_box(self.scr, y, 0, 3, W, color=C_BORDER)

        slabel = (self.G.nodes[self.start_id]["label"]
                  if self.start_id else "─ not set ─")
        sa = (curses.color_pair(C_START_TAG) | curses.A_BOLD
              if self.start_id else curses.color_pair(C_DIM))
        safe_addstr(self.scr, y + 1, 2,  "START ▶ ",
                    curses.color_pair(C_NORMAL) | curses.A_BOLD)
        safe_addstr(self.scr, y + 1, 10, slabel[:lw - 12], sa)
        safe_addstr(self.scr, y + 1, lw, "│", curses.color_pair(C_BORDER))

        elabel = ("  ·  ".join(self.G.nodes[e]["label"] for e in self.end_ids)
                  if self.end_ids else "─ not set ─")
        ea = (curses.color_pair(C_END_TAG) | curses.A_BOLD
              if self.end_ids else curses.color_pair(C_DIM))
        safe_addstr(self.scr, y + 1, lw + 2, "END(S) ▶ ",
                    curses.color_pair(C_NORMAL) | curses.A_BOLD)
        safe_addstr(self.scr, y + 1, lw + 11, elabel[:W - lw - 13], ea)

        if self.focus == "start":
            safe_addstr(self.scr, y, 2, "[ setting START ]",
                        curses.color_pair(C_START_TAG) | curses.A_BOLD)
        else:
            safe_addstr(self.scr, y, lw + 2, "[ adding ENDS ]",
                        curses.color_pair(C_END_TAG) | curses.A_BOLD)
            safe_addstr(self.scr, y + 1, W - 22,
                        "[BKSP] remove last end",
                        curses.color_pair(C_DIM))

    # ── draw: topic list ─────────────────────────────────────────

    def draw_topic_list(self):
        H, W, lw, rw = self.dimensions()
        list_h   = H - 6
        list_top = 1
        draw_box(self.scr, list_top, 0, list_h, lw,
                 title="TOPICS", color=C_BORDER)

        if self.filter_str:
            fi = f" /{self.filter_str}/ ({len(self.filtered)}) "
            safe_addstr(self.scr, list_top, lw - len(fi) - 2, fi,
                        curses.color_pair(C_HIGHLIGHT) | curses.A_BOLD)

        inner_h = list_h - 2
        inner_w = lw - 4

        if self.cursor < self.scroll:
            self.scroll = self.cursor
        if self.cursor >= self.scroll + inner_h:
            self.scroll = self.cursor - inner_h + 1

        for row, idx in enumerate(
            self.filtered[self.scroll: self.scroll + inner_h]
        ):
            t     = self.topics[idx]
            ry    = list_top + 1 + row
            cat   = t["category"]
            glyph = CATEGORY_GLYPH.get(cat, "·")
            is_cursor = (self.scroll + row) == self.cursor
            is_start  = t["id"] == self.start_id
            is_end    = t["id"] in self.end_ids

            bg = (curses.color_pair(C_SELECTED) | curses.A_BOLD
                  if is_cursor else curses.color_pair(C_NORMAL))
            safe_addstr(self.scr, ry, 2, " " * inner_w, bg)
            ga = (bg if is_cursor
                  else curses.color_pair(CATEGORY_COLOR.get(cat, C_NORMAL)) | curses.A_BOLD)
            safe_addstr(self.scr, ry, 2, glyph, ga)

            xo = 4
            if is_start:
                safe_addstr(self.scr, ry, xo, " S ",
                            curses.color_pair(C_START_TAG) | curses.A_BOLD)
                xo += 4
            elif is_end:
                tag = f" E{self.end_ids.index(t['id'])+1} "
                safe_addstr(self.scr, ry, xo, tag,
                            curses.color_pair(C_END_TAG) | curses.A_BOLD)
                xo += len(tag) + 1

            lbl = t["label"][:inner_w - xo + 2]
            q   = self.filter_str.lower()
            if q and not is_cursor:
                lo = lbl.lower()
                ms = lo.find(q)
                if ms >= 0:
                    safe_addstr(self.scr, ry, xo, lbl[:ms], bg)
                    safe_addstr(self.scr, ry, xo + ms,
                                lbl[ms:ms + len(q)],
                                curses.color_pair(C_HIGHLIGHT) | curses.A_BOLD)
                    safe_addstr(self.scr, ry, xo + ms + len(q),
                                lbl[ms + len(q):], bg)
                else:
                    safe_addstr(self.scr, ry, xo, lbl, bg)
            else:
                safe_addstr(self.scr, ry, xo, lbl, bg)

        # scrollbar
        if len(self.filtered) > inner_h:
            sb_h = max(1, inner_h * inner_h // len(self.filtered))
            sb_y = (self.scroll * (inner_h - sb_h)
                    // max(1, len(self.filtered) - inner_h))
            for row in range(inner_h):
                ch = "█" if sb_y <= row < sb_y + sb_h else "░"
                safe_addstr(self.scr, list_top + 1 + row, lw - 2, ch,
                            curses.color_pair(C_DIM))

    # ── line builders ────────────────────────────────────────────

    def _topic_detail_lines(self, topic_id, width):
        """Right-panel content when browsing (no active result)."""
        G     = self.G
        lines = []

        def add(text="", attr=0):
            lines.append(("TEXT", text[:width], attr))

        def sep():
            add("─" * (width - 1), curses.color_pair(C_DIM))

        node  = G.nodes[topic_id]
        label = node.get("label", "")
        cat   = node.get("category", "unknown")
        glyph = CATEGORY_GLYPH.get(cat, "·")
        ca    = curses.color_pair(CATEGORY_COLOR.get(cat, C_NORMAL)) | curses.A_BOLD

        add()
        lines.append(("HEADING", glyph, label, ca))
        add()
        cat_label = CATEGORY_LABELS.get(cat, cat)
        add(f"  Category  :  {cat_label}", ca)
        in_d  = G.in_degree(topic_id)
        out_d = G.out_degree(topic_id)
        add(f"  Prereqs   :  {in_d}     Leads to  :  {out_d}",
            curses.color_pair(C_DIM))

        preds = list(G.predecessors(topic_id))
        if preds:
            add()
            add("  PREREQUISITES", curses.color_pair(C_SECTION_HDR) | curses.A_BOLD)
            sep()
            for p in preds:
                add(f"    ◂  {G.nodes[p]['label']}", curses.color_pair(C_DIM))

        succs = list(G.successors(topic_id))
        if succs:
            add()
            add("  LEADS TO", curses.color_pair(C_SECTION_HDR) | curses.A_BOLD)
            sep()
            for s in succs:
                add(f"    ▸  {G.nodes[s]['label']}", curses.color_pair(C_DIM))

        blist = self.books.get(topic_id, [])
        add()
        add(f"  BOOKS & RESOURCES  ({len(blist)})",
            curses.color_pair(C_SECTION_HDR) | curses.A_BOLD)
        sep()
        if blist:
            for b in blist:
                lines.append(("BOOK", b, 2))   # indent=2
        else:
            add("  No books listed.", curses.color_pair(C_DIM))
        add()
        return lines

    def _result_lines(self, width):
        """Right-panel content when a path result is active."""
        G    = self.G
        r    = self.result
        mode = self.result_mode
        lines = []

        def add(text="", attr=0):
            lines.append(("TEXT", text[:width], attr))

        def sep():
            add("─" * (width - 1), curses.color_pair(C_DIM))

        def add_node(i, nid, is_goal, is_shared, is_last, conn="├──"):
            lbl   = G.nodes[nid].get("label", nid) if nid in G else nid
            cat   = G.nodes[nid].get("category", "unknown") if nid in G else "unknown"
            glyph = CATEGORY_GLYPH.get(cat, "·")
            step  = f"  {i:>2}  {conn} "
            lines.append(("STEP", step, glyph, lbl, cat, is_goal, is_shared))
            if not is_last:
                add(f"  {'':>2}  │", curses.color_pair(C_DIM))
            blist = self.books.get(nid, [])
            for b in blist:
                lines.append(("BOOK", b, 9))   # indent=9
            if blist and not is_last:
                add(f"  {'':>2}  │", curses.color_pair(C_DIM))

        if mode == "single":
            if not r["found"]:
                add("  ✗ No path found.",
                    curses.color_pair(C_ERROR) | curses.A_BOLD)
                add(f"  {r['error']}", curses.color_pair(C_ERROR))
                return lines
            path = r["path"]
            add(f"  Steps: {len(path)}   Weight: {r['total_weight']}",
                curses.color_pair(C_SUCCESS) | curses.A_BOLD)
            sep()
            for i, nid in enumerate(path):
                il = i == len(path) - 1
                add_node(i + 1, nid, il, False, il, "└──" if il else "├──")

        elif mode == "multi":
            merged  = r.get("merged_nodes", [])
            shared  = r.get("shared_nodes", set())
            targets = r.get("target_nodes", set())
            for err in r.get("errors", []):
                add(f"  ⚠  {err}", curses.color_pair(C_ERROR))
            add(f"  Unique steps: {len(merged)}   Shared: {len(shared)}",
                curses.color_pair(C_SUCCESS) | curses.A_BOLD)
            sep()
            for i, nid in enumerate(merged):
                il = i == len(merged) - 1
                ig = nid in targets
                ish = nid in shared and not ig
                add_node(i + 1, nid, ig, ish, il, "└──" if il else "├──")
            sep()
            for tid, pr in r.get("individual_paths", {}).items():
                tl = G.nodes[tid].get("label", tid) if tid in G else tid
                if pr["found"]:
                    add(f"  ✓  {tl}  ({len(pr['path'])} steps)",
                        curses.color_pair(C_SUCCESS) | curses.A_BOLD)
                else:
                    add(f"  ✗  {tl}", curses.color_pair(C_ERROR))

        elif mode == "greedy":
            segs = r.get("segments", [])
            for err in r.get("errors", []):
                add(f"  ⚠  {err}", curses.color_pair(C_ERROR))
            add(f"  Goals: {len(segs)}   Weight: {r.get('total_weight',0)}",
                curses.color_pair(C_SUCCESS) | curses.A_BOLD)
            step = 1
            for seg in segs:
                sep()
                fl = G.nodes[seg["from"]].get("label", seg["from"]) if seg["from"] in G else seg["from"]
                tl = G.nodes[seg["to"]].get("label", seg["to"])     if seg["to"] in G   else seg["to"]
                add(f"  ── {fl}  →  {tl}  (w:{seg['weight']})",
                    curses.color_pair(C_OPT_REC) | curses.A_BOLD)
                add()
                path = seg["path"]
                for j, nid in enumerate(path):
                    ig = nid == seg["to"]
                    il = j == len(path) - 1
                    add_node(step, nid, ig, False, il, "──▶")
                    step += 1

        return lines

    # ── draw: right panel ────────────────────────────────────────

    def draw_right_panel(self):
        H, W, lw, rw = self.dimensions()
        ph  = H - 6
        pt  = 1
        px  = lw
        pw  = rw

        draw_box(self.scr, pt, px, ph, pw,
                 title="DETAIL / ROADMAP", color=C_BORDER)

        inner_h = ph - 2
        inner_w = pw - 4
        t = self.current_topic()

        if self.result:
            lines = self._result_lines(inner_w)
        elif t:
            lines = self._topic_detail_lines(t["id"], inner_w)
        else:
            lines = [("TEXT", "  Select a topic on the left.",
                      curses.color_pair(C_DIM))]

        max_scroll = max(0, len(lines) - inner_h)
        self.result_scroll = max(0, min(self.result_scroll, max_scroll))

        if max_scroll > 0:
            hint = f" +/- ({self.result_scroll+1}/{len(lines)}) "
            safe_addstr(self.scr, pt + ph - 1,
                        px + pw - len(hint) - 2, hint,
                        curses.color_pair(C_DIM))

        for row, entry in enumerate(
            lines[self.result_scroll: self.result_scroll + inner_h]
        ):
            ry = pt + 1 + row
            rx = px + 2
            safe_addstr(self.scr, ry, rx, " " * inner_w,
                        curses.color_pair(C_NORMAL))
            kind = entry[0]

            if kind == "TEXT":
                _, text, attr = entry
                safe_addstr(self.scr, ry, rx, text, attr)

            elif kind == "HEADING":
                _, glyph, label, ca = entry
                safe_addstr(self.scr, ry, rx, glyph, ca)
                safe_addstr(self.scr, ry, rx + 2, label,
                            curses.color_pair(C_TITLE) | curses.A_BOLD)

            elif kind == "STEP":
                _, step, glyph, lbl, cat, is_goal, is_shared = entry
                cx = rx
                safe_addstr(self.scr, ry, cx, step,
                            curses.color_pair(C_DIM))
                cx += len(step)
                safe_addstr(self.scr, ry, cx, glyph,
                            curses.color_pair(CATEGORY_COLOR.get(cat, C_NORMAL)) | curses.A_BOLD)
                cx += 2
                if is_goal:
                    safe_addstr(self.scr, ry, cx, " ★ ",
                                curses.color_pair(C_GOAL) | curses.A_BOLD)
                    cx += 3
                elif is_shared:
                    safe_addstr(self.scr, ry, cx, " ◈ ",
                                curses.color_pair(C_SHARED) | curses.A_BOLD)
                    cx += 3
                safe_addstr(self.scr, ry, cx, lbl[:rx + inner_w - cx],
                            curses.color_pair(C_NORMAL))

            elif kind == "BOOK":
                _, b, indent = entry
                cat    = b.get("category", "unknown")
                title  = b.get("title",  "")
                author = b.get("author", "")
                glyph  = BOOK_GLYPH.get(cat, "[?]")
                ca     = curses.color_pair(CATEGORY_COLOR.get(cat, C_NORMAL))
                cx     = rx + indent
                safe_addstr(self.scr, ry, cx, glyph, ca)
                cx += len(glyph) + 1
                avail = rx + inner_w - cx - 1
                if author:
                    author_str = f"  — {author}"
                    tmax = max(4, avail - len(author_str))
                    t_out = (title[:tmax - 1] + "…"
                             if len(title) > tmax else title)
                    safe_addstr(self.scr, ry, cx, t_out,
                                curses.color_pair(C_BOOK_TITLE) | curses.A_BOLD)
                    cx += len(t_out)
                    safe_addstr(self.scr, ry, cx,
                                author_str[:rx + inner_w - cx],
                                curses.color_pair(C_BOOK_AUTHOR))
                else:
                    safe_addstr(self.scr, ry, cx, title[:avail],
                                curses.color_pair(C_BOOK_TITLE) | curses.A_BOLD)

    # ── draw all ─────────────────────────────────────────────────

    def draw_all(self):
        self.scr.erase()
        self.draw_header()
        self.draw_topic_list()
        self.draw_right_panel()
        self.draw_selection_bar()
        self.draw_footer()
        self.scr.refresh()

    # ── pathfinder ───────────────────────────────────────────────

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
            else:
                self.result = greedy_multi_target(self.G, self.start_id, self.end_ids)
            self.result_mode   = mode
            self.result_scroll = 0
            ok = (self.result.get("found", False) if mode == "single"
                  else self.result.get("all_found", False))
            self.set_status(
                "Path found!  Use +/- to scroll." if ok
                else "Partial — some paths not found.",
                ok=ok,
            )
        except Exception as e:
            self.set_status(f"Error: {e}", ok=False)

    # ── input ────────────────────────────────────────────────────

    def handle_key(self, key):
        H, W, lw, rw = self.dimensions()
        inner_h = H - 8

        if self.searching:
            if key == 27:
                self.searching = False
                self.search_buf = self.filter_str = ""
                self.apply_filter()
            elif key in (10, 13, curses.KEY_ENTER):
                self.searching = False
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

        if key in (ord('q'), ord('Q')):
            self.running = False
        elif key == ord('/'):
            self.searching = True
            self.search_buf = self.filter_str
        elif key == 27:
            self.filter_str = self.search_buf = ""
            self.apply_filter()
            self.result = self.result_mode = None
        elif key == curses.KEY_UP:
            prev = self.cursor
            self.cursor = max(0, self.cursor - 1)
            if self.cursor != prev:
                self.result_scroll = 0
        elif key == curses.KEY_DOWN:
            prev = self.cursor
            self.cursor = min(len(self.filtered) - 1, self.cursor + 1)
            if self.cursor != prev:
                self.result_scroll = 0
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - inner_h)
            self.result_scroll = 0
        elif key == curses.KEY_NPAGE:
            self.cursor = min(len(self.filtered) - 1, self.cursor + inner_h)
            self.result_scroll = 0
        elif key == curses.KEY_HOME:
            self.cursor = self.scroll = 0
        elif key == curses.KEY_END:
            self.cursor = max(0, len(self.filtered) - 1)
        elif key == 9:  # TAB
            self.focus = "end" if self.focus == "start" else "start"
            self.set_status(
                "Focus: setting START" if self.focus == "start"
                else "Focus: adding END topics", ok=True)
        elif key in (10, 13, curses.KEY_ENTER):
            t = self.current_topic()
            if t:
                if self.focus == "start":
                    self.start_id = t["id"]
                    self.result   = None
                    self.set_status(f"Start set: {t['label']}", ok=True)
                    self.focus = "end"
                else:
                    if t["id"] == self.start_id:
                        self.set_status("Cannot use START as END.", ok=False)
                    elif t["id"] in self.end_ids:
                        self.set_status("Already in end list.", ok=False)
                    else:
                        self.end_ids.append(t["id"])
                        self.result = None
                        self.set_status(
                            f"End added: {t['label']}  ({len(self.end_ids)} total)",
                            ok=True)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if self.focus == "end" and self.end_ids:
                rem = self.G.nodes[self.end_ids.pop()]["label"]
                self.result = None
                self.set_status(f"Removed: {rem}", ok=True)
        elif key in (ord('m'), ord('M')):
            self.mode_idx = (self.mode_idx + 1) % len(MODE_NAMES)
            self.set_status(f"Mode: {MODE_DESC[MODE_NAMES[self.mode_idx]]}", ok=True)
        elif key in (ord('r'), ord('R'), curses.KEY_F5):
            self.run_pathfinder()
        elif key in (ord('+'), ord('=')):
            self.result_scroll += 1
        elif key == ord('-'):
            self.result_scroll = max(0, self.result_scroll - 1)

    # ── main loop ────────────────────────────────────────────────

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
# Entry
# ─────────────────────────────────────────────────────────────────

def launch(drawio_path):
    def _run(stdscr):
        MathRoadmapTUI(stdscr, drawio_path).run()
    curses.wrapper(_run)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Math Roadmap TUI")
    p.add_argument("--file", "-f", default="mathematics-roadmap.drawio")
    args = p.parse_args()
    if not os.path.exists(args.file):
        print(f"Error: file not found: {args.file}")
        sys.exit(1)
    launch(args.file)
