#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Disk usage treemap — Python stdlib only (Tkinter)."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

sys.setrecursionlimit(10_000)

# ── Palette ───────────────────────────────────────────────────────────────────

_COLORS = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
]
_BG = "#1e1e2e"
_FG = "#cdd6f4"
_BTN_BG = "#313244"
_BTN_ACTIVE = "#45475a"
_MUTED = "#6c7086"
_LOADING_FG = "#cba6f7"


# ── Helpers ───────────────────────────────────────────────────────────────────


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def open_in_files(path: str) -> None:
    """Reveal path in the OS file manager."""
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
    elif sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
    else:
        subprocess.run(["explorer", "/select,", path], check=False)


# ── Filesystem scan ───────────────────────────────────────────────────────────


def _scan(path: str) -> list[dict]:
    """Recursively build a tree of {name, path, size, is_dir, children} dicts."""
    items: list[dict] = []
    try:
        entries = list(os.scandir(path))
    except PermissionError, OSError:
        return items
    for e in entries:
        try:
            if e.is_symlink():
                continue
            if e.is_file(follow_symlinks=False):
                sz = e.stat(follow_symlinks=False).st_size
                items.append(
                    dict(name=e.name, path=e.path, size=sz, is_dir=False, children=[])
                )
            elif e.is_dir(follow_symlinks=False):
                children = _scan(e.path)
                sz = sum(c["size"] for c in children)
                items.append(
                    dict(
                        name=e.name,
                        path=e.path,
                        size=sz,
                        is_dir=True,
                        children=children,
                    )
                )
        except OSError, PermissionError:
            pass
    items.sort(key=lambda x: x["size"], reverse=True)
    return items


# ── Squarified treemap layout ─────────────────────────────────────────────────


def _worst_ratio(areas: list[float], side: float) -> float:
    """Worst aspect ratio for the given row areas and shortest canvas side."""
    if not areas or side == 0:
        return float("inf")
    s = sum(areas)
    if s == 0:
        return float("inf")
    mx, mn = max(areas), min(areas)
    return max(side * side * mx / (s * s), s * s / (side * side * mn))


def _emit_row(row: list[tuple], x: float, y: float, w: float, h: float):
    """Yield (item, x, y, w, h) for one committed row."""
    s = sum(a for _, a in row)
    if w >= h:
        col_w = s / h if h else 0
        cy = y
        for item, a in row:
            ih = a / col_w if col_w else 0
            yield item, x, cy, col_w, ih
            cy += ih
    else:
        row_h = s / w if w else 0
        cx = x
        for item, a in row:
            iw = a / row_h if row_h else 0
            yield item, cx, y, iw, row_h
            cx += iw


def squarify(items: list[dict], x: float, y: float, w: float, h: float):
    """Yield (item, x, y, w, h) using the squarified treemap algorithm."""
    if not items or w < 1 or h < 1:
        return
    total = sum(it["size"] for it in items)
    if not total:
        return
    area = w * h
    normed = [(it, it["size"] / total * area) for it in items]
    normed.sort(key=lambda t: t[1], reverse=True)

    row: list[tuple] = []
    rx, ry, rw, rh = x, y, w, h

    for entry in normed:
        cur_a = [a for _, a in row]
        new_a = cur_a + [entry[1]]
        if not row or _worst_ratio(new_a, min(rw, rh)) <= _worst_ratio(
            cur_a, min(rw, rh)
        ):
            row.append(entry)
        else:
            yield from _emit_row(row, rx, ry, rw, rh)
            s = sum(a for _, a in row)
            if rw >= rh:
                d = s / rh if rh else 0
                rx += d
                rw -= d
            else:
                d = s / rw if rw else 0
                ry += d
                rh -= d
            row = [entry]
    if row:
        yield from _emit_row(row, rx, ry, rw, rh)


# ── Application ───────────────────────────────────────────────────────────────


class DiskTreemap(tk.Tk):
    _PAD = 2  # gap between cells (px)

    def __init__(self, start: str | None = None):
        super().__init__()
        self.title("Disk Treemap")
        self.geometry("1200x750")
        self.configure(bg=_BG)
        self.minsize(400, 300)

        # Navigation stack: list of (path_label, items)
        self._stack: list[tuple[str, list]] = []
        self._items: list[dict] = []
        # Rendered cells: (item, rect_canvas_id, text_canvas_id_or_None)
        self._cells: list[tuple[dict, int, int | None]] = []
        self._q: queue.Queue = queue.Queue()

        self._build_ui()
        root = start or str(Path.home())
        self.after(50, lambda: self._start_scan(root))

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Toolbar ──────────────────────────────────────────────────────────
        bar = tk.Frame(self, bg=_BG, pady=6)
        bar.pack(fill=tk.X, padx=10)

        def _btn(text: str, cmd) -> tk.Button:
            b = tk.Button(
                bar,
                text=text,
                command=cmd,
                bg=_BTN_BG,
                fg=_FG,
                relief=tk.FLAT,
                activebackground=_BTN_ACTIVE,
                activeforeground=_FG,
                padx=10,
                pady=4,
                cursor="hand2",
            )
            b.pack(side=tk.LEFT, padx=(0, 4))
            return b

        self._btn_up = _btn("▲  Up", self._go_up)
        _btn("⏏  Open…", self._open_dir)

        self._lbl_path = tk.Label(
            bar, text="", bg=_BG, fg=_MUTED, font=("Courier", 11), anchor=tk.W
        )
        self._lbl_path.pack(side=tk.LEFT, padx=12, fill=tk.X, expand=True)

        # ── Canvas ────────────────────────────────────────────────────────────
        self._canvas = tk.Canvas(self, bg=_BG, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 0))
        self._canvas.bind("<Configure>", lambda _: self._redraw())
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Leave>", self._on_leave)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Double-Button-1>", self._on_double_click)

        # ── Status bar ────────────────────────────────────────────────────────
        sb = tk.Frame(self, bg=_BG, pady=4)
        sb.pack(fill=tk.X, padx=10, side=tk.BOTTOM)
        self._lbl_status = tk.Label(
            sb, text="", bg=_BG, fg=_MUTED, font=("Courier", 10), anchor=tk.W
        )
        self._lbl_status.pack(side=tk.LEFT)

        # ── Loading label (overlaid on canvas via place) ───────────────────
        self._lbl_loading = tk.Label(
            self, text="Scanning…", bg=_BG, fg=_LOADING_FG, font=("Courier", 20)
        )

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _start_scan(self, path: str) -> None:
        self._lbl_path.config(text=path)
        self._show_loading(True)
        self._canvas.delete("all")
        self._cells = []

        def _worker() -> None:
            items = _scan(path)
            self._q.put(("done", items))

        threading.Thread(target=_worker, daemon=True).start()
        self._poll_queue()

    def _poll_queue(self) -> None:
        try:
            _, items = self._q.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue)
            return
        self._show_loading(False)
        self._items = items
        if not items:
            cw = self._canvas.winfo_width()
            ch = self._canvas.winfo_height()
            self._canvas.create_text(
                cw // 2,
                ch // 2,
                text="(empty or permission denied)",
                fill=_MUTED,
                font=("Courier", 14),
            )
            return
        self._redraw()

    def _show_loading(self, show: bool) -> None:
        if show:
            self._lbl_loading.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            self._lbl_loading.place_forget()

    # ── Draw ──────────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        if not self._items:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 4 or ch < 4:
            return
        self._canvas.delete("all")
        self._cells = []
        P = self._PAD
        for i, (item, rx, ry, rw, rh) in enumerate(squarify(self._items, 0, 0, cw, ch)):
            ix, iy = rx + P, ry + P
            iw, ih = rw - 2 * P, rh - 2 * P
            if iw < 2 or ih < 2:
                continue
            color = _COLORS[i % len(_COLORS)]
            rid = self._canvas.create_rectangle(
                ix,
                iy,
                ix + iw,
                iy + ih,
                fill=color,
                outline=_BG,
                width=1,
            )
            tid = None
            if iw > 18 and ih > 12:
                fs = max(8, min(13, int(min(iw, ih) / 6)))
                label = item["name"]
                if iw > 60 and ih > 28:
                    label += f"\n{fmt_bytes(item['size'])}"
                weight = "bold" if item["is_dir"] else "normal"
                tid = self._canvas.create_text(
                    ix + iw / 2,
                    iy + ih / 2,
                    text=label,
                    fill="white",
                    font=("Helvetica", fs, weight),
                    width=iw - 6,
                    anchor=tk.CENTER,
                )
            self._cells.append((item, rid, tid))

    # ── Events ────────────────────────────────────────────────────────────────

    def _cell_at(self, event: tk.Event) -> dict | None:
        hits = self._canvas.find_overlapping(event.x, event.y, event.x, event.y)
        if not hits:
            return None
        top = hits[-1]
        for item, rid, tid in self._cells:
            if rid == top or (tid is not None and tid == top):
                return item
        return None

    def _on_motion(self, event: tk.Event) -> None:
        item = self._cell_at(event)
        if item:
            icon = "▶ " if item["is_dir"] else "  "
            hint = (
                "  (click to drill in)" if item["is_dir"] and item["children"] else ""
            )
            self._lbl_status.config(
                text=f"{icon}{item['path']}  —  {fmt_bytes(item['size'])}{hint}"
            )
        else:
            self._lbl_status.config(text="")

    def _on_leave(self, _event: tk.Event) -> None:
        self._lbl_status.config(text="")

    def _on_click(self, event: tk.Event) -> None:
        item = self._cell_at(event)
        if item and item["is_dir"] and item["children"]:
            self._stack.append((self._lbl_path.cget("text"), self._items))
            self._lbl_path.config(text=item["path"])
            self._items = item["children"]
            self._redraw()

    def _on_double_click(self, event: tk.Event) -> None:
        item = self._cell_at(event)
        if item:
            open_in_files(item["path"])

    def _go_up(self) -> None:
        if self._stack:
            path, items = self._stack.pop()
            self._lbl_path.config(text=path)
            self._items = items
            self._redraw()

    def _open_dir(self) -> None:
        d = filedialog.askdirectory(title="Select directory to scan")
        if d:
            self._stack.clear()
            self._start_scan(d)


if __name__ == "__main__":
    start_path = sys.argv[1] if len(sys.argv) > 1 else None
    DiskTreemap(start=start_path).mainloop()
