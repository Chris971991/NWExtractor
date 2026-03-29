"""NWExtractor GUI — Scan → Filter → Extract workflow.

Primary UX: cascading filter dropdowns that navigate the game's asset tree.
  [Content ▼] → [Sub-type ▼] → [Detail ▼] → [Asset Type ▼]
  Results: 1,234 files (450 MB)  [Extract These]

Secondary: tree view below for granular browsing/selection.
"""

import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

import customtkinter as ctk

from nwextractor.pak.extractor import PakExtractor
from nwextractor.pak.catalog import (
    scan_paks, AssetCatalog, DirNode, FileEntry,
    build_directory_tree, _make_display_name, ASSET_CATEGORIES,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#D4912A"
ACCENT_HOVER = "#E5A33B"
BG_DARK = "#1A1A2E"
BG_PANEL = "#16213E"
BG_INPUT = "#0F3460"
BG_LOG = "#0D1117"
BG_TREE = "#0D1117"
TEXT_COLOR = "#E0E0E0"
TEXT_DIM = "#888"
GREEN = "#2EA043"

ALL = "All"

# Asset type groups for the filter dropdown
ASSET_TYPE_GROUPS = {
    "All": None,
    "Models": {".cgf", ".cga", ".cgam", ".skin", ".chr", ".cgfheap"},
    "Textures": {".dds", ".tif", ".tiff", ".png", ".jpg", ".tga"},
    "Animations": {".caf", ".anm", ".i_caf"},
    "Materials": {".mtl", ".material"},
    "Audio": {".wem", ".bnk", ".ogg", ".wav"},
    "Data": {".json", ".xml", ".csv", ".lua", ".luac", ".datasheet"},
    "Heightmaps": {".heightmap", ".h32", ".raw"},
}


def _find_oodle_dll(game_path: Path) -> Path | None:
    """Auto-find the Oodle DLL from the user's system.

    New World has Oodle statically linked, so we find the DLL from
    other installed games/engines. Runs automatically — no user action needed.
    """
    import subprocess

    # 1. Quick: check next to our exe / cwd
    for name in ("oo2core_9_win64.dll", "oo2core_8_win64.dll"):
        for loc in (Path.cwd(), game_path, Path(__file__).parent):
            p = loc / name
            if p.exists():
                return p

    # 2. Use Windows 'where' to check PATH
    try:
        result = subprocess.run(
            ["where", "/R", "C:\\", "oo2core_9_win64.dll"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            if lines:
                return Path(lines[0])
    except Exception:
        pass

    # 3. Search known locations (Steam libraries, Epic/UE installs)
    # Find all Steam library folders from libraryfolders.vdf
    steam_commons = _find_steam_libraries()
    search_dirs = steam_commons + [
        Path("C:/Program Files/Epic Games"),
        Path("D:/Program Files/Epic Games"),
    ]

    for loc in search_dirs:
        if not loc.exists():
            continue
        try:
            matches = list(loc.rglob("oo2core_*_win64.dll"))
            if matches:
                matches.sort(key=lambda p: p.name, reverse=True)
                return matches[0]
        except PermissionError:
            continue

    return None


def _find_steam_libraries() -> list[Path]:
    """Find all Steam library folders from Steam's config."""
    libraries = []
    # Default Steam location
    default = Path("C:/Program Files (x86)/Steam")
    if default.exists():
        libraries.append(default / "steamapps" / "common")

    # Parse libraryfolders.vdf for additional libraries
    vdf = default / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        try:
            text = vdf.read_text(errors="ignore")
            import re
            # Match "path" entries in the VDF
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                p = Path(match.group(1)) / "steamapps" / "common"
                if p.exists() and p not in libraries:
                    libraries.append(p)
        except Exception:
            pass

    # Common additional drive letters
    for drive in "DEFGH":
        for pattern in [f"{drive}:/SteamLibrary/steamapps/common",
                        f"{drive}:/Steam/steamapps/common",
                        f"{drive}:/Games/Steam/steamapps/common"]:
            p = Path(pattern)
            if p.exists() and p not in libraries:
                libraries.append(p)

    return libraries


def _mip_suffixes() -> list[str]:
    """Generate all possible mip file suffixes (.1 through .9, .1a through .9a)."""
    suffixes = []
    for i in range(1, 15):
        suffixes.append(f".{i}")
    for i in range(1, 15):
        suffixes.append(f".{i}a")
    return suffixes


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 ** 3:
        return f"{n / 1024**2:.1f} MB"
    else:
        return f"{n / 1024**3:.2f} GB"


def _configure_tree_style():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.Treeview",
                     background=BG_TREE, foreground=TEXT_COLOR,
                     fieldbackground=BG_TREE, borderwidth=0,
                     font=("Segoe UI", 10), rowheight=24)
    style.configure("Dark.Treeview.Heading",
                     background=BG_PANEL, foreground=ACCENT,
                     font=("Segoe UI", 10, "bold"), borderwidth=0)
    style.map("Dark.Treeview",
              background=[("selected", "#1F3A60")],
              foreground=[("selected", "#FFFFFF")])


class NWExtractorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("NWExtractor — New World Asset Extractor for UE5")
        self.geometry("1100x850")
        self.minsize(900, 650)
        self.configure(fg_color=BG_DARK)

        self._working = False
        self._stop_requested = False
        self._catalog: AssetCatalog | None = None

        # Filter state — each level stores the DirNode for the current selection
        self._filter_nodes: list[DirNode | None] = [None, None, None, None]

        self._build_ui()

    def _build_ui(self):
        # ── Header ──
        header = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="NWExtractor",
                     font=ctk.CTkFont(size=20, weight="bold"), text_color=ACCENT,
                     ).pack(side="left", padx=16, pady=6)
        ctk.CTkLabel(header, text="New World Asset Extractor for UE5",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
                     ).pack(side="left", padx=4)

        # ── Paths ──
        paths = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8)
        paths.pack(fill="x", padx=12, pady=(8, 4))
        paths.grid_columnconfigure(1, weight=1)

        self._game_dir_var = ctk.StringVar()
        self._add_path_row(paths, "Game Directory", self._game_dir_var, self._browse_game_dir, 0)
        self._output_dir_var = ctk.StringVar(value=str(Path.cwd() / "extracted"))
        self._add_path_row(paths, "Output Directory", self._output_dir_var, self._browse_output_dir, 1)

        # ── Scan button ──
        scan_row = ctk.CTkFrame(self, fg_color="transparent")
        scan_row.pack(fill="x", padx=12, pady=(2, 4))

        self._scan_btn = ctk.CTkButton(
            scan_row, text="Scan Game Files", command=self._on_scan,
            font=ctk.CTkFont(size=13, weight="bold"), height=36,
            fg_color="#1F6FEB", hover_color="#388BFD", corner_radius=8,
        )
        self._scan_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            scan_row, text="Stop", command=self._on_stop,
            font=ctk.CTkFont(size=13), height=36,
            fg_color="#8B0000", hover_color="#A52A2A", corner_radius=8,
            state="disabled",
        )
        self._stop_btn.pack(side="left")

        # ── Filter panel (hidden until scan completes) ──
        self._filter_panel = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8)
        # Don't pack yet — shown after scan

        # Filter row 1: cascading dropdowns
        filter_row1 = ctk.CTkFrame(self._filter_panel, fg_color="transparent")
        filter_row1.pack(fill="x", padx=12, pady=(10, 4))

        self._dropdown_vars = []
        self._dropdown_widgets = []
        self._dropdown_labels = ["Content", "Sub-type", "Detail", "Specific"]

        for i, label in enumerate(self._dropdown_labels):
            ctk.CTkLabel(filter_row1, text=f"{label}:",
                         font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
                         ).pack(side="left", padx=(8 if i > 0 else 0, 2))

            var = ctk.StringVar(value=ALL)
            self._dropdown_vars.append(var)

            dd = ctk.CTkOptionMenu(
                filter_row1, variable=var, values=[ALL],
                font=ctk.CTkFont(size=12), height=32, width=160,
                fg_color=BG_INPUT, button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
                dropdown_fg_color=BG_PANEL,
                command=lambda val, idx=i: self._on_filter_changed(idx),
                state="disabled",
            )
            dd.pack(side="left", padx=(0, 4))
            self._dropdown_widgets.append(dd)

        # Filter row 2: asset type + search + results
        filter_row2 = ctk.CTkFrame(self._filter_panel, fg_color="transparent")
        filter_row2.pack(fill="x", padx=12, pady=(2, 10))

        ctk.CTkLabel(filter_row2, text="Asset Type:",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
                     ).pack(side="left", padx=(0, 2))

        self._asset_type_var = ctk.StringVar(value=ALL)
        self._asset_type_dd = ctk.CTkOptionMenu(
            filter_row2, variable=self._asset_type_var,
            values=list(ASSET_TYPE_GROUPS.keys()),
            font=ctk.CTkFont(size=12), height=32, width=130,
            fg_color=BG_INPUT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=BG_PANEL,
            command=lambda val: self._update_results(),
        )
        self._asset_type_dd.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(filter_row2, text="Search:",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
                     ).pack(side="left", padx=(0, 2))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._update_results())
        ctk.CTkEntry(
            filter_row2, textvariable=self._search_var, width=200,
            placeholder_text="e.g. dynasty, pirate, oak...",
            fg_color=BG_INPUT, border_color=ACCENT,
        ).pack(side="left", padx=(0, 16))

        # Results summary + extract button
        self._results_var = ctk.StringVar(value="")
        self._results_label = ctk.CTkLabel(
            filter_row2, textvariable=self._results_var,
            font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT,
        )
        self._results_label.pack(side="left", padx=(0, 10))

        self._extract_btn = ctk.CTkButton(
            filter_row2, text="Extract These", command=self._on_extract,
            font=ctk.CTkFont(size=13, weight="bold"), height=34,
            fg_color=GREEN, hover_color="#3FB950", text_color="white",
            corner_radius=8, state="disabled",
        )
        self._extract_btn.pack(side="right")

        # Filter row 3: conversion options
        filter_row3 = ctk.CTkFrame(self._filter_panel, fg_color="transparent")
        filter_row3.pack(fill="x", padx=12, pady=(0, 10))

        self._convert_textures_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            filter_row3, text="Convert DDS textures to", variable=self._convert_textures_var,
            font=ctk.CTkFont(size=11), fg_color=ACCENT, hover_color=ACCENT_HOVER,
            checkbox_width=18, checkbox_height=18,
        ).pack(side="left", padx=(0, 4))

        self._texture_format_var = ctk.StringVar(value="PNG")
        ctk.CTkOptionMenu(
            filter_row3, variable=self._texture_format_var,
            values=["PNG", "TGA", "Keep DDS"],
            font=ctk.CTkFont(size=11), height=28, width=100,
            fg_color=BG_INPUT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=BG_PANEL,
        ).pack(side="left", padx=(0, 12))

        self._auto_normals_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            filter_row3, text="Auto-detect normal maps → TGA",
            variable=self._auto_normals_var,
            font=ctk.CTkFont(size=11), fg_color=ACCENT, hover_color=ACCENT_HOVER,
            checkbox_width=18, checkbox_height=18,
        ).pack(side="left", padx=(0, 12))

        # Separator
        ctk.CTkLabel(filter_row3, text="  |  ",
                     font=ctk.CTkFont(size=11), text_color="#444",
                     ).pack(side="left")

        self._convert_models_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            filter_row3, text="Convert models to",
            variable=self._convert_models_var,
            font=ctk.CTkFont(size=11), fg_color=ACCENT, hover_color=ACCENT_HOVER,
            checkbox_width=18, checkbox_height=18,
        ).pack(side="left", padx=(0, 4))

        self._model_format_var = ctk.StringVar(value="GLB")
        ctk.CTkOptionMenu(
            filter_row3, variable=self._model_format_var,
            values=["GLB", "OBJ"],
            font=ctk.CTkFont(size=11), height=28, width=80,
            fg_color=BG_INPUT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=BG_PANEL,
        ).pack(side="left", padx=(0, 4))

        # ── Main split: tree (left) + log (right) ──
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(0, weight=1)

        # Left: results tree
        tree_panel = ctk.CTkFrame(main, fg_color=BG_PANEL, corner_radius=8)
        tree_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        tree_header_row = ctk.CTkFrame(tree_panel, fg_color="transparent")
        tree_header_row.pack(fill="x", padx=10, pady=(8, 4))

        self._tree_header_var = ctk.StringVar(value="Scan game files to get started")
        ctk.CTkLabel(tree_header_row, textvariable=self._tree_header_var,
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_COLOR, anchor="w",
                     ).pack(side="left")

        ctk.CTkButton(
            tree_header_row, text="Deselect All", command=self._tree_deselect_all, width=80,
            font=ctk.CTkFont(size=11), height=24,
            fg_color="#333", hover_color="#555", corner_radius=4,
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            tree_header_row, text="Select All", command=self._tree_select_all, width=70,
            font=ctk.CTkFont(size=11), height=24,
            fg_color="#333", hover_color="#555", corner_radius=4,
        ).pack(side="right", padx=(4, 0))

        _configure_tree_style()
        tree_frame = tk.Frame(tree_panel, bg=BG_TREE)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._tree = ttk.Treeview(
            tree_frame, style="Dark.Treeview",
            columns=("count", "size"), selectmode="none",
            show="tree headings",
        )
        self._tree.heading("#0", text="Path", anchor="w")
        self._tree.heading("count", text="Files", anchor="e")
        self._tree.heading("size", text="Size", anchor="e")
        self._tree.column("#0", width=400, stretch=True)
        self._tree.column("count", width=80, stretch=False, anchor="e")
        self._tree.column("size", width=90, stretch=False, anchor="e")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        self._tree.bind("<<TreeviewOpen>>", self._on_tree_expand)
        self._tree.bind("<Button-1>", self._on_tree_click)
        self._tree_nodes: dict[str, DirNode] = {}  # item_id → DirNode
        self._tree_files: dict[str, FileEntry] = {}  # item_id → FileEntry
        self._tree_checked: dict[str, bool] = {}  # item_id → checked state
        self._tree_populated: set[str] = set()

        # Right: log
        log_panel = ctk.CTkFrame(main, fg_color=BG_PANEL, corner_radius=8)
        log_panel.grid(row=0, column=1, sticky="nsew")

        log_h = ctk.CTkFrame(log_panel, fg_color="transparent")
        log_h.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(log_h, text="Log", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_COLOR).pack(side="left")
        ctk.CTkButton(log_h, text="Clear", command=self._clear_log, width=45,
                      font=ctk.CTkFont(size=10), height=22,
                      fg_color="#333", hover_color="#555", corner_radius=4).pack(side="right")

        self._log_text = ctk.CTkTextbox(
            log_panel, font=ctk.CTkFont(family="Consolas", size=10),
            fg_color=BG_LOG, text_color="#C9D1D9", corner_radius=6, wrap="word",
        )
        self._log_text.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # ── Bottom: progress ──
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(0, 8))

        self._progress_var = ctk.DoubleVar(value=0)
        ctk.CTkProgressBar(
            bottom, variable=self._progress_var,
            progress_color=ACCENT, fg_color=BG_INPUT, height=6,
        ).pack(fill="x", pady=(0, 2))

        self._status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(bottom, textvariable=self._status_var,
                     font=ctk.CTkFont(size=10), text_color=TEXT_DIM, anchor="w",
                     ).pack(fill="x")

    # ── Helpers ──

    def _add_path_row(self, parent, label, var, browse_fn, row):
        ctk.CTkLabel(parent, text=f"{label}:", font=ctk.CTkFont(size=11),
                     anchor="e", width=110,
                     ).grid(row=row, column=0, padx=(10, 4), pady=5, sticky="e")
        ctk.CTkEntry(parent, textvariable=var, fg_color=BG_INPUT, border_color=ACCENT,
                     ).grid(row=row, column=1, padx=4, pady=5, sticky="ew")
        ctk.CTkButton(parent, text="Browse", command=browse_fn, width=65,
                      fg_color="#333", hover_color="#555", corner_radius=6,
                      font=ctk.CTkFont(size=11),
                      ).grid(row=row, column=2, padx=(4, 10), pady=5)

    def _browse_game_dir(self):
        path = filedialog.askdirectory(title="Select New World Game Directory")
        if path:
            self._game_dir_var.set(path)
            self._log(f"Game directory: {path}")

    def _browse_output_dir(self):
        path = filedialog.askdirectory(title="Select Output Directory")
        if path:
            self._output_dir_var.set(path)

    def _log(self, msg: str):
        def _do():
            self._log_text.insert("end", msg + "\n")
            self._log_text.see("end")
        self.after(0, _do)

    def _clear_log(self):
        self._log_text.delete("1.0", "end")

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status_var.set(msg))

    def _set_progress(self, v: float):
        self.after(0, lambda: self._progress_var.set(v))

    # ── Scanning ──

    def _on_scan(self):
        if self._working:
            return
        game_dir = self._game_dir_var.get().strip()
        if not game_dir or not Path(game_dir).exists():
            self._log("ERROR: Select a valid game directory.")
            return
        self._working = True
        self._stop_requested = False
        self._scan_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._set_progress(0)
        threading.Thread(target=self._run_scan, args=(Path(game_dir),), daemon=True).start()

    def _run_scan(self, game_path: Path):
        try:
            assets_dir = game_path / "assets" if (game_path / "assets").exists() else game_path
            self._set_status("Scanning pak files...")
            catalog = scan_paks(assets_dir, log_fn=self._log, stop_check=lambda: self._stop_requested)
            self._catalog = catalog
            self._set_progress(1.0)
            self._set_status(f"Scan complete — {catalog.total_files:,} files found")
            self.after(0, self._on_scan_complete)
        except Exception as e:
            self._log(f"SCAN ERROR: {e}")
            self._set_status("Scan failed")
        finally:
            self._working = False
            self.after(0, lambda: self._scan_btn.configure(state="normal"))
            self.after(0, lambda: self._stop_btn.configure(state="disabled"))

    def _on_scan_complete(self):
        """Populate filter dropdowns after scan."""
        if not self._catalog or not self._catalog.dir_tree:
            return

        # Show filter panel
        self._filter_panel.pack(fill="x", padx=12, pady=(0, 4), after=self._scan_btn.master)

        root = self._catalog.dir_tree
        self._filter_nodes[0] = root

        # Populate first dropdown with top-level dirs
        children = root.sorted_children()
        names = [ALL] + [c.display_name for c in children]
        self._dropdown_widgets[0].configure(values=names, state="normal")
        self._dropdown_vars[0].set(ALL)

        # Reset others
        for i in range(1, 4):
            self._dropdown_widgets[i].configure(values=[ALL], state="disabled")
            self._dropdown_vars[i].set(ALL)

        self._extract_btn.configure(state="normal")
        self._update_results()

    # ── Filter logic ──

    def _get_node_by_display_name(self, parent_node: DirNode, display_name: str) -> DirNode | None:
        """Find a child node by its display name."""
        for child in parent_node.children.values():
            if child.display_name == display_name:
                return child
        return None

    def _on_filter_changed(self, level: int):
        """Handle dropdown change at a given level."""
        if not self._catalog or not self._catalog.dir_tree:
            return

        # Determine the selected node at this level
        selected_name = self._dropdown_vars[level].get()

        if level == 0:
            parent = self._catalog.dir_tree
        else:
            parent = self._filter_nodes[level]

        if selected_name == ALL or parent is None:
            selected_node = parent or self._catalog.dir_tree
        else:
            selected_node = self._get_node_by_display_name(
                parent if level == 0 else self._filter_nodes[level],
                selected_name,
            )
            if selected_node is None:
                selected_node = parent

        # Handle level 0 specially — parent is always root
        if level == 0:
            if selected_name == ALL:
                selected_node = self._catalog.dir_tree
            else:
                selected_node = self._get_node_by_display_name(self._catalog.dir_tree, selected_name)
                if not selected_node:
                    selected_node = self._catalog.dir_tree

        # Store node for next level
        next_level = level + 1
        if next_level < 4:
            self._filter_nodes[next_level] = selected_node

            # Populate next dropdown from this node's children
            if selected_node and selected_node.children:
                children = selected_node.sorted_children()
                names = [ALL] + [c.display_name for c in children]
                self._dropdown_widgets[next_level].configure(values=names, state="normal")
            else:
                self._dropdown_widgets[next_level].configure(values=[ALL], state="disabled")
            self._dropdown_vars[next_level].set(ALL)

            # Reset all deeper levels
            for i in range(next_level + 1, 4):
                self._dropdown_widgets[i].configure(values=[ALL], state="disabled")
                self._dropdown_vars[i].set(ALL)
                self._filter_nodes[i] = None

        self._update_results()

    def _get_filtered_node(self) -> DirNode | None:
        """Walk the dropdown selections to find the deepest selected node."""
        if not self._catalog or not self._catalog.dir_tree:
            return None

        node = self._catalog.dir_tree

        for level in range(4):
            val = self._dropdown_vars[level].get()
            if val == ALL:
                break
            child = self._get_node_by_display_name(node, val)
            if child:
                node = child
            else:
                break

        return node

    def _get_filtered_files(self) -> list[FileEntry]:
        """Get files matching current filter selections."""
        node = self._get_filtered_node()
        if not node:
            return []

        files = node.get_all_files()

        # Apply asset type filter
        asset_type = self._asset_type_var.get()
        if asset_type != ALL:
            exts = ASSET_TYPE_GROUPS.get(asset_type)
            if exts:
                files = [f for f in files if Path(f.path).suffix.lower() in exts]

        # Apply search filter
        search = self._search_var.get().strip().lower()
        if search:
            terms = search.split()
            files = [f for f in files if all(t in f.path.lower() for t in terms)]

        return files

    def _update_results(self):
        """Update results count and tree view based on current filters."""
        files = self._get_filtered_files()
        total_size = sum(f.uncompressed_size for f in files)
        self._results_var.set(f"{len(files):,} files  ({_fmt_size(total_size)})")

        # Update tree header
        node = self._get_filtered_node()
        path_desc = node.display_name if node and node.name != "(root)" else "All Assets"
        asset_type = self._asset_type_var.get()
        if asset_type != ALL:
            path_desc += f" → {asset_type}"
        self._tree_header_var.set(f"Browsing: {path_desc}")

        # Rebuild tree view with filtered subtree
        self._rebuild_tree(node, files)

    def _rebuild_tree(self, node: DirNode | None, files: list[FileEntry]):
        """Rebuild the treeview showing the filtered content."""
        self._tree.delete(*self._tree.get_children())
        self._tree_nodes.clear()
        self._tree_files.clear()
        self._tree_checked.clear()
        self._tree_populated.clear()

        if not node:
            return

        # If filtering by asset type or search, build a filtered sub-tree
        asset_type = self._asset_type_var.get()
        search = self._search_var.get().strip().lower()
        filtering = asset_type != ALL or bool(search)

        if filtering:
            file_set = set(id(f) for f in files)
            self._insert_filtered_tree("", node, file_set, depth=0, max_depth=3)
        else:
            for child in node.sorted_children():
                self._insert_tree_node("", child)
            for fe in sorted(node.files, key=lambda f: f.path.lower()):
                self._insert_tree_file("", fe)

    def _check_text(self, checked: bool) -> str:
        return "\u2611" if checked else "\u2610"

    def _insert_tree_node(self, parent_id: str, node: DirNode, checked: bool = True) -> str:
        item_id = self._tree.insert(
            parent_id, "end",
            text=f" {self._check_text(checked)}  \U0001F4C1  {node.display_name}",
            values=(f"{node.total_count:,}", _fmt_size(node.total_size)),
            open=False,
        )
        self._tree_nodes[item_id] = node
        self._tree_checked[item_id] = checked
        if node.children or node.files:
            self._tree.insert(item_id, "end", text="...")
        return item_id

    def _insert_tree_file(self, parent_id: str, fe: FileEntry, checked: bool = True):
        name = fe.path.rsplit("/", 1)[-1] if "/" in fe.path else fe.path
        item_id = self._tree.insert(
            parent_id, "end",
            text=f" {self._check_text(checked)}  \U0001F4C4  {name}",
            values=("", _fmt_size(fe.uncompressed_size)),
        )
        self._tree_files[item_id] = fe
        self._tree_checked[item_id] = checked

    def _insert_filtered_tree(self, parent_id: str, node: DirNode, file_set: set,
                               depth: int, max_depth: int, checked: bool = True):
        """Insert tree nodes, only showing branches that contain filtered files."""
        matching_here = [f for f in node.files if id(f) in file_set]
        matching_below = sum(1 for f in node.get_all_files() if id(f) in file_set)

        if matching_below == 0:
            return

        if node.name != "(root)":
            item_id = self._tree.insert(
                parent_id, "end",
                text=f" {self._check_text(checked)}  \U0001F4C1  {node.display_name}",
                values=(f"{matching_below:,}", ""),
                open=depth < 2,
            )
            self._tree_nodes[item_id] = node
            self._tree_checked[item_id] = checked
        else:
            item_id = parent_id

        if depth < max_depth:
            for child in node.sorted_children():
                pid = item_id if node.name != "(root)" else ""
                self._insert_filtered_tree(pid, child, file_set, depth + 1, max_depth, checked)

        for fe in sorted(matching_here, key=lambda f: f.path.lower()):
            pid = item_id if node.name != "(root)" else ""
            self._insert_tree_file(pid, fe, checked)

    def _on_tree_expand(self, event):
        item_id = self._tree.focus()
        if item_id in self._tree_populated:
            return
        self._tree_populated.add(item_id)
        node = self._tree_nodes.get(item_id)
        if not node:
            return
        parent_checked = self._tree_checked.get(item_id, True)
        for child in self._tree.get_children(item_id):
            self._tree.delete(child)
        for child_node in node.sorted_children():
            self._insert_tree_node(item_id, child_node, checked=parent_checked)
        for fe in sorted(node.files, key=lambda f: f.path.lower()):
            self._insert_tree_file(item_id, fe, checked=parent_checked)

    def _on_tree_click(self, event):
        """Toggle checkbox on click."""
        item_id = self._tree.identify_row(event.y)
        if not item_id:
            return
        # Only toggle on clicks in the tree column (not count/size columns)
        col = self._tree.identify_column(event.x)
        if col != "#0":
            return

        # Check if this item has a checkbox (is it in our tracking dicts?)
        if item_id not in self._tree_checked:
            return

        # Toggle
        new_state = not self._tree_checked[item_id]
        self._set_item_checked(item_id, new_state)
        self._update_extract_count()

    def _set_item_checked(self, item_id: str, checked: bool):
        """Set checked state on an item and all its children."""
        self._tree_checked[item_id] = checked

        # Update display text
        old_text = self._tree.item(item_id, "text")
        # Replace checkbox character
        if "\u2611" in old_text or "\u2610" in old_text:
            new_text = old_text.replace("\u2611" if not checked else "\u2610",
                                        self._check_text(checked))
            self._tree.item(item_id, text=new_text)

        # Cascade to children
        for child_id in self._tree.get_children(item_id):
            if child_id in self._tree_checked:
                self._set_item_checked(child_id, checked)

    def _get_checked_files(self) -> list[FileEntry]:
        """Get all files that are checked in the tree."""
        result = []

        # Collect explicitly checked file items
        for item_id, fe in self._tree_files.items():
            if self._tree_checked.get(item_id, True):
                result.append(fe)

        # Collect files from checked folder nodes that haven't been expanded
        # (their children aren't in the tree yet, so we need to grab from the node)
        for item_id, node in self._tree_nodes.items():
            if not self._tree_checked.get(item_id, True):
                continue
            if item_id in self._tree_populated:
                continue  # Already expanded — children are tracked individually
            # Not expanded but checked — include all files from this node
            asset_type = self._asset_type_var.get()
            search = self._search_var.get().strip().lower()
            for f in node.get_all_files():
                if asset_type != ALL:
                    exts = ASSET_TYPE_GROUPS.get(asset_type)
                    if exts and Path(f.path).suffix.lower() not in exts:
                        continue
                if search:
                    terms = search.split()
                    if not all(t in f.path.lower() for t in terms):
                        continue
                result.append(f)

        # Deduplicate by path
        seen = set()
        deduped = []
        for f in result:
            if f.path not in seen:
                seen.add(f.path)
                deduped.append(f)
        return deduped

    def _tree_select_all(self):
        """Check all items in the tree."""
        for item_id in self._tree_checked:
            self._set_item_checked(item_id, True)
        self._update_extract_count()

    def _tree_deselect_all(self):
        """Uncheck all items in the tree."""
        for item_id in self._tree_checked:
            self._set_item_checked(item_id, False)
        self._update_extract_count()

    def _update_extract_count(self):
        """Update the results label to reflect checked items."""
        files = self._get_checked_files()
        total_size = sum(f.uncompressed_size for f in files)
        self._results_var.set(f"{len(files):,} files  ({_fmt_size(total_size)})")

    # ── Extraction ──

    def _on_extract(self):
        if self._working or not self._catalog:
            return
        output_dir = self._output_dir_var.get().strip()
        game_dir = self._game_dir_var.get().strip()
        if not output_dir:
            self._log("ERROR: Select an output directory.")
            return

        files = self._get_checked_files()
        if not files:
            self._log("ERROR: No files selected. Check items in the tree.")
            return

        game_path = Path(game_dir)
        oodle_path = _find_oodle_dll(game_path)
        if oodle_path:
            self._log(f"Using Oodle DLL: {oodle_path}")
        else:
            self._log("ERROR: Could not auto-find oo2core_9_win64.dll on your system.")
            self._log("  Copy it from any UE5 game into: " + str(Path.cwd()))
            self._set_status("Oodle DLL not found")
            self._working = False
            self.after(0, lambda: self._extract_btn.configure(state="normal"))
            self.after(0, lambda: self._scan_btn.configure(state="normal"))
            self.after(0, lambda: self._stop_btn.configure(state="disabled"))
            return

        self._working = True
        self._stop_requested = False
        self._extract_btn.configure(state="disabled")
        self._scan_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._set_progress(0)

        self._log(f"\nExtracting {len(files):,} files...")

        threading.Thread(
            target=self._run_extraction,
            args=(files, Path(output_dir), oodle_path),
            daemon=True,
        ).start()

    def _on_stop(self):
        self._stop_requested = True
        self._log("Stopping...")

    def _run_extraction(self, selected_files: list[FileEntry], output_dir: Path, oodle_path: Path):
        from nwextractor.pak.azcs import is_azcs, decompress_azcs
        from nwextractor.convert.textures import convert_texture, FORMAT_PNG, FORMAT_TGA
        from nwextractor.convert.models import convert_model

        convert_dds = self._convert_textures_var.get()
        convert_models = self._convert_models_var.get()
        tex_fmt_str = self._texture_format_var.get()
        auto_normals = self._auto_normals_var.get()

        if tex_fmt_str == "PNG":
            tex_fmt = FORMAT_PNG
        elif tex_fmt_str == "TGA":
            tex_fmt = FORMAT_TGA
        else:
            convert_dds = False
            tex_fmt = FORMAT_PNG

        try:
            extractor = PakExtractor(oodle_dll=oodle_path)

            # Build a global index: path → (pak_file, FileEntry) for mip lookups
            # Using the catalog's all_files which already has every file across all paks
            mip_index: dict[str, str] = {}  # path → pak_file
            if convert_dds and self._catalog:
                self._set_status("Building mip file index...")
                for fe in self._catalog.all_files:
                    # Index .dds.1, .dds.2, etc. and .dds.1a, .dds.2a, etc.
                    if ".dds." in fe.path:
                        mip_index[fe.path] = fe.pak_file

            # --- Phase 1: Extract selected files ---
            self._log("\n--- Phase 1: Extracting files ---")
            by_pak: dict[str, list] = {}
            for fe in selected_files:
                by_pak.setdefault(fe.pak_file, []).append(fe)

            total = len(selected_files)
            done = 0
            errors = 0
            dds_headers: list[Path] = []  # Track DDS files for phase 2
            model_files: list[Path] = []  # Track model files for phase 3
            anim_files: list[Path] = []   # Track animation files for phase 4
            mtl_files: list[Path] = []    # Track material files for phase 5
            heightmap_files: list[Path] = []  # Track heightmaps for phase 6

            for pak_str, files_in_pak in by_pak.items():
                if self._stop_requested:
                    break

                pak_path = Path(pak_str)
                self._log(f"── {pak_path.name} ({len(files_in_pak)} files) ──")

                try:
                    data = pak_path.read_bytes()
                    entries = extractor._read_central_directory(data)
                except Exception as e:
                    self._log(f"  ERROR: {e}")
                    errors += len(files_in_pak)
                    done += len(files_in_pak)
                    continue

                entry_map = {e.path: e for e in entries if not e.is_directory}

                for fe in files_in_pak:
                    if self._stop_requested:
                        break
                    done += 1
                    self._set_progress(done / total * 0.5)  # Phase 1 = first 50%
                    self._set_status(f"Extracting {done:,}/{total:,}")

                    entry = entry_map.get(fe.path)
                    if not entry:
                        errors += 1
                        continue

                    try:
                        file_data = extractor._extract_file_data(data, entry)
                        if is_azcs(file_data):
                            file_data = decompress_azcs(file_data)
                    except Exception as e:
                        self._log(f"  SKIP {fe.path}: {e}")
                        errors += 1
                        continue

                    out_path = output_dir / fe.path
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(file_data)

                    if out_path.suffix.lower() == ".dds":
                        dds_headers.append(out_path)
                    elif convert_models and out_path.suffix.lower() in (".cgf", ".cga", ".skin"):
                        model_files.append(out_path)
                    elif convert_models and out_path.suffix.lower() == ".caf":
                        anim_files.append(out_path)
                    elif convert_models and out_path.suffix.lower() == ".mtl":
                        mtl_files.append(out_path)
                    elif out_path.suffix.lower() == ".heightmap":
                        heightmap_files.append(out_path)

            # --- Phase 2: Extract mips and convert textures ---
            if convert_dds and dds_headers and not self._stop_requested:
                self._log(f"\n--- Phase 2: Extracting mips & converting {len(dds_headers)} textures ---")

                # Collect all needed mip paths and which paks they're in
                mips_needed: dict[str, list[str]] = {}  # pak_path → [mip_paths]
                for dds_out in dds_headers:
                    dds_rel = str(dds_out.relative_to(output_dir)).replace("\\", "/")
                    for suffix in _mip_suffixes():
                        mip_rel = f"{dds_rel}{suffix}"
                        pak_file = mip_index.get(mip_rel)
                        if pak_file:
                            mips_needed.setdefault(pak_file, []).append(mip_rel)

                # Extract mips from each pak that has them
                mip_total = sum(len(v) for v in mips_needed.values())
                mip_done = 0
                for pak_str, mip_paths in mips_needed.items():
                    if self._stop_requested:
                        break

                    pak_path = Path(pak_str)
                    try:
                        data = pak_path.read_bytes()
                        entries = extractor._read_central_directory(data)
                    except Exception:
                        mip_done += len(mip_paths)
                        continue

                    entry_map = {e.path: e for e in entries if not e.is_directory}

                    for mip_rel in mip_paths:
                        if self._stop_requested:
                            break
                        mip_done += 1
                        self._set_progress(0.5 + (mip_done / max(mip_total, 1)) * 0.3)
                        self._set_status(f"Fetching mips {mip_done:,}/{mip_total:,}")

                        entry = entry_map.get(mip_rel)
                        if not entry:
                            continue
                        try:
                            mip_data = extractor._extract_file_data(data, entry)
                            if is_azcs(mip_data):
                                mip_data = decompress_azcs(mip_data)
                            mip_out = output_dir / mip_rel
                            mip_out.parent.mkdir(parents=True, exist_ok=True)
                            mip_out.write_bytes(mip_data)
                        except Exception:
                            pass

                # Convert all DDS textures
                self._log("\nConverting textures...")
                converted = 0
                for i, dds_out in enumerate(dds_headers):
                    if self._stop_requested:
                        break
                    self._set_progress(0.8 + (i / len(dds_headers)) * 0.2)
                    self._set_status(f"Converting {i+1:,}/{len(dds_headers):,}")

                    try:
                        result = convert_texture(
                            dds_out, dds_out.parent,
                            output_format=tex_fmt,
                            auto_detect_normals=auto_normals,
                        )
                        if result:
                            converted += 1
                            # Clean up raw files
                            dds_out.unlink(missing_ok=True)
                            for suffix in _mip_suffixes():
                                mip_file = dds_out.parent / f"{dds_out.name}{suffix}"
                                if mip_file.exists():
                                    mip_file.unlink()
                    except Exception as e:
                        self._log(f"  CONVERT FAIL {dds_out.name}: {e}")

                self._log(f"Converted {converted:,}/{len(dds_headers):,} textures to {tex_fmt.upper()}")

            # --- Phase 3: Convert materials to UE5 JSON (before models, to avoid .mtl conflicts) ---
            if convert_models and mtl_files and not self._stop_requested:
                from nwextractor.convert.materials import convert_material
                self._log(f"\n--- Phase 3: Converting {len(mtl_files)} materials ---")
                mtls_converted = 0
                for i, mtl_path in enumerate(mtl_files):
                    if self._stop_requested:
                        break
                    try:
                        result = convert_material(mtl_path, mtl_path.parent)
                        if result:
                            mtls_converted += 1
                    except Exception as e:
                        self._log(f"  MTL FAIL {mtl_path.name}: {e}")
                self._log(f"Converted {mtls_converted:,}/{len(mtl_files):,} materials to JSON")

            # --- Phase 4: Convert models ---
            if convert_models and model_files and not self._stop_requested:
                model_fmt = self._model_format_var.get()
                self._log(f"\n--- Phase 4: Converting {len(model_files)} models to {model_fmt} ---")
                models_converted = 0
                for i, model_path in enumerate(model_files):
                    if self._stop_requested:
                        break
                    self._set_status(f"Converting model {i+1:,}/{len(model_files):,}")
                    try:
                        result = convert_model(model_path, model_path.parent, output_format=model_fmt.lower())
                        if result:
                            models_converted += 1
                    except Exception as e:
                        self._log(f"  MODEL FAIL {model_path.name}: {e}")
                self._log(f"Converted {models_converted:,}/{len(model_files):,} models to {model_fmt}")

            # --- Phase 5: Convert animations to GLB ---
            if convert_models and anim_files and not self._stop_requested:
                from nwextractor.convert.models import convert_animation
                self._log(f"\n--- Phase 5: Converting {len(anim_files)} animations to GLB ---")
                anims_converted = 0
                for i, anim_path in enumerate(anim_files):
                    if self._stop_requested:
                        break
                    self._set_status(f"Converting animation {i+1:,}/{len(anim_files):,}")
                    try:
                        result = convert_animation(anim_path, anim_path.parent)
                        if result:
                            anims_converted += 1
                    except Exception as e:
                        self._log(f"  ANIM FAIL {anim_path.name}: {e}")
                self._log(f"Converted {anims_converted:,}/{len(anim_files):,} animations to GLB")

            # --- Phase 6: Convert heightmaps to R16 ---
            if heightmap_files and not self._stop_requested:
                from nwextractor.convert.heightmaps import convert_heightmap
                self._log(f"\n--- Phase 6: Converting {len(heightmap_files)} heightmaps to R16 ---")
                hm_converted = 0
                for i, hm_path in enumerate(heightmap_files):
                    if self._stop_requested:
                        break
                    try:
                        result = convert_heightmap(hm_path, hm_path.parent, output_format="r16")
                        if result:
                            hm_converted += 1
                    except Exception as e:
                        self._log(f"  HEIGHTMAP FAIL {hm_path.name}: {e}")
                self._log(f"Converted {hm_converted:,}/{len(heightmap_files):,} heightmaps to R16")

            self._set_progress(1.0)
            self._log(f"\nDone! Extracted {done - errors:,} files ({errors} errors)")
            self._set_status(f"Done — {done - errors:,} files extracted")

        except Exception as e:
            self._log(f"\nFATAL ERROR: {e}")
            self._set_status("Error")
        finally:
            self._working = False
            self.after(0, lambda: self._extract_btn.configure(state="normal"))
            self.after(0, lambda: self._scan_btn.configure(state="normal"))
            self.after(0, lambda: self._stop_btn.configure(state="disabled"))


def run():
    app = NWExtractorApp()
    app.mainloop()


if __name__ == "__main__":
    run()
