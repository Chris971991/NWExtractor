"""Asset catalog — scans pak files and categorizes contents by asset type and content tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nwextractor.pak.extractor import PakExtractor, CentralDirEntry

# Extension → (category, sub_type) mapping
ASSET_CATEGORIES: dict[str, tuple[str, str]] = {
    # Textures
    ".dds": ("Textures", "DDS"),
    ".tif": ("Textures", "TIF"),
    ".tiff": ("Textures", "TIFF"),
    ".png": ("Textures", "PNG"),
    ".jpg": ("Textures", "JPG"),
    ".jpeg": ("Textures", "JPEG"),
    ".tga": ("Textures", "TGA"),
    # Models
    ".cgf": ("Models", "CGF (Static Geometry)"),
    ".cga": ("Models", "CGA (Animated Geometry)"),
    ".cgam": ("Models", "CGAM (Anim Geometry Data)"),
    ".skin": ("Models", "SKIN (Skinned Mesh)"),
    ".chr": ("Models", "CHR (Character/Skeleton)"),
    # Animations
    ".caf": ("Animations", "CAF (Character Animation)"),
    ".anm": ("Animations", "ANM (Animation)"),
    ".i_caf": ("Animations", "I_CAF (Intermediate Anim)"),
    # Materials
    ".mtl": ("Materials", "MTL (Material)"),
    ".material": ("Materials", "Material"),
    # Audio
    ".wem": ("Audio", "WEM (Wwise Audio)"),
    ".bnk": ("Audio", "BNK (Wwise Bank)"),
    ".ogg": ("Audio", "OGG"),
    ".wav": ("Audio", "WAV"),
    # Levels / Maps
    ".cry": ("Levels", "CRY (Level)"),
    ".lyr": ("Levels", "LYR (Layer)"),
    ".vegmap": ("Levels", "VEGMAP (Vegetation)"),
    ".entities_xml": ("Levels", "Entity Placements"),
    # Data
    ".json": ("Data", "JSON"),
    ".xml": ("Data", "XML"),
    ".csv": ("Data", "CSV"),
    ".lua": ("Data", "LUA (Script)"),
    ".luac": ("Data", "LUAC (Compiled Script)"),
    ".datasheet": ("Data", "Datasheet"),
    # Shaders
    ".cfx": ("Shaders", "CFX (Shader)"),
    ".cfi": ("Shaders", "CFI (Shader Include)"),
    ".fxcb": ("Shaders", "FXCB (Compiled Shader)"),
    # UI
    ".uicanvas": ("UI", "UI Canvas"),
    ".sprite": ("UI", "Sprite"),
    ".font": ("UI", "Font"),
    ".fontfamily": ("UI", "Font Family"),
}


@dataclass
class FileEntry:
    """A single file found in a pak archive."""
    path: str
    pak_file: str
    compressed_size: int
    uncompressed_size: int
    category: str
    sub_type: str


@dataclass
class SubTypeInfo:
    """Aggregated info for a sub-type within a category."""
    name: str
    files: list[FileEntry] = field(default_factory=list)
    selected: bool = True

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def total_size(self) -> int:
        return sum(f.uncompressed_size for f in self.files)


@dataclass
class CategoryInfo:
    """Aggregated info for an asset category."""
    name: str
    sub_types: dict[str, SubTypeInfo] = field(default_factory=dict)
    selected: bool = True

    @property
    def count(self) -> int:
        return sum(st.count for st in self.sub_types.values())

    @property
    def total_size(self) -> int:
        return sum(st.total_size for st in self.sub_types.values())


@dataclass
class DirNode:
    """A node in the directory tree built from pak file paths.

    Supports lazy traversal — children are pre-built during scan, but the
    GUI only needs to read one level at a time for lazy-loading tree views.
    """
    name: str
    display_name: str = ""  # Friendly name (set by smart labeling)
    children: dict[str, DirNode] = field(default_factory=dict)
    files: list[FileEntry] = field(default_factory=list)
    selected: bool = True
    _total_count: int | None = field(default=None, repr=False)
    _total_size: int | None = field(default=None, repr=False)

    def __post_init__(self):
        if not self.display_name:
            self.display_name = _make_display_name(self.name)

    @property
    def total_count(self) -> int:
        if self._total_count is None:
            self._total_count = len(self.files) + sum(c.total_count for c in self.children.values())
        return self._total_count

    @property
    def total_size(self) -> int:
        if self._total_size is None:
            self._total_size = (sum(f.uncompressed_size for f in self.files)
                                + sum(c.total_size for c in self.children.values()))
        return self._total_size

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def get_all_files(self) -> list[FileEntry]:
        """Recursively collect all files under this node."""
        result = list(self.files)
        for child in self.children.values():
            result.extend(child.get_all_files())
        return result

    def get_selected_files(self) -> list[FileEntry]:
        """Recursively collect files under selected nodes."""
        if not self.selected:
            return []
        result = list(self.files)
        for child in self.children.values():
            result.extend(child.get_selected_files())
        return result

    def sorted_children(self) -> list[DirNode]:
        """Return children sorted: directories first, then by name."""
        return sorted(self.children.values(), key=lambda c: (c.is_leaf, c.name.lower()))


# Smart display name mapping for known New World directory patterns
_DISPLAY_NAMES: dict[str, str] = {
    "objects": "Game Objects",
    "characters": "Characters",
    "player": "Player Characters",
    "npc": "NPCs",
    "creatures": "Creatures",
    "weapons": "Weapons",
    "armor": "Armor",
    "skins": "Skins",
    "costumes": "Costumes",
    "props": "Props",
    "furniture": "Furniture",
    "housing": "Housing",
    "environments": "Environments",
    "vegetation": "Vegetation",
    "terrain": "Terrain",
    "levels": "Levels / Maps",
    "sounds": "Sound Effects",
    "music": "Music",
    "audio": "Audio",
    "animations": "Animations",
    "textures": "Textures",
    "materials": "Materials",
    "effects": "Effects / VFX",
    "particles": "Particles",
    "ui": "User Interface",
    "libs": "Libraries",
    "scripts": "Scripts",
    "shaders": "Shaders",
    "fonts": "Fonts",
    "cinematics": "Cinematics",
    "cutscenes": "Cutscenes",
    "loot": "Loot",
    "consumables": "Consumables",
    "resources": "Resources",
    "tools": "Tools",
    "ammo": "Ammunition",
    "sword": "Sword", "greatsword": "Greatsword",
    "hatchet": "Hatchet", "axe": "Axe", "greataxe": "Great Axe",
    "hammer": "War Hammer", "warhammer": "War Hammer",
    "spear": "Spear", "rapier": "Rapier",
    "bow": "Bow", "musket": "Musket", "blunderbuss": "Blunderbuss",
    "firestaff": "Fire Staff", "lifestaff": "Life Staff",
    "icegauntlet": "Ice Gauntlet", "voidgauntlet": "Void Gauntlet",
    "flail": "Flail", "shield": "Shield",
    "male": "Male", "female": "Female",
    "head": "Head", "chest": "Chest", "legs": "Legs",
    "hands": "Hands", "feet": "Feet",
    "light": "Light Armor", "medium": "Medium Armor", "heavy": "Heavy Armor",
    "corrupted": "Corrupted", "angry_earth": "Angry Earth",
    "ancients": "Ancients", "lost": "The Lost",
    "withered": "Withered", "varangian": "Varangian",
    "dynasty": "Dynasty", "beast": "Beasts",
}


def _make_display_name(name: str) -> str:
    """Convert a directory name to a human-readable display name."""
    lower = name.lower().replace("-", "").replace("_", "")
    if lower in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[lower]
    # Title-case with underscore/hyphen splitting
    return name.replace("_", " ").replace("-", " ").title()


# Directories whose children should be promoted to the top level.
# e.g. "objects" contains characters, weapons, crafting — those should
# appear directly in the first filter dropdown, not buried under "Game Objects".
_FLATTEN_DIRS = {"objects"}


def build_directory_tree(files: list[FileEntry]) -> DirNode:
    """Build a directory tree from a flat list of file entries."""
    root = DirNode(name="(root)", display_name="All Assets")

    for fe in files:
        parts = fe.path.replace("\\", "/").split("/")
        node = root
        for part in parts[:-1]:
            if part not in node.children:
                node.children[part] = DirNode(name=part)
            node = node.children[part]
        node.files.append(fe)

    # Flatten container directories: promote their children to root level
    for flat_name in _FLATTEN_DIRS:
        if flat_name in root.children:
            container = root.children.pop(flat_name)
            for child_name, child_node in container.children.items():
                # Avoid name collisions with existing root children
                if child_name in root.children:
                    child_name = f"{flat_name}_{child_name}"
                root.children[child_name] = child_node
            # Any files directly in the container go into root
            root.files.extend(container.files)

    return root


@dataclass
class AssetCatalog:
    """Complete catalog of assets found in game pak files."""
    categories: dict[str, CategoryInfo] = field(default_factory=dict)
    all_files: list[FileEntry] = field(default_factory=list)
    dir_tree: DirNode | None = field(default=None)
    pak_count: int = 0

    @property
    def total_files(self) -> int:
        return len(self.all_files)

    def get_selected_files(self) -> list[FileEntry]:
        """Return only files in selected categories/sub-types."""
        selected = []
        for cat in self.categories.values():
            if not cat.selected:
                continue
            for st in cat.sub_types.values():
                if st.selected:
                    selected.extend(st.files)
        return selected

    def get_selected_from_tree(self) -> list[FileEntry]:
        """Return selected files based on directory tree selection."""
        if self.dir_tree:
            return self.dir_tree.get_selected_files()
        return []


def _classify(path: str) -> tuple[str, str]:
    """Classify a file path into (category, sub_type)."""
    ext = Path(path).suffix.lower()
    if ext in ASSET_CATEGORIES:
        return ASSET_CATEGORIES[ext]
    return ("Other", ext.upper().lstrip(".") if ext else "No Extension")


def scan_paks(assets_dir: Path, log_fn=None, stop_check=None) -> AssetCatalog:
    """Scan all pak files and build an asset catalog (no extraction, just indexing).

    This reads the ZIP central directories of all .pak files to build
    a categorized index of every file. It's fast because it doesn't
    decompress or extract anything.

    Args:
        assets_dir: Directory containing .pak files (searched recursively).
        log_fn: Optional logging callback.
        stop_check: Optional callable returning True to abort.

    Returns:
        AssetCatalog with all files categorized.
    """
    log = log_fn or (lambda msg: None)
    catalog = AssetCatalog()

    pak_files = sorted(assets_dir.rglob("*.pak"))
    catalog.pak_count = len(pak_files)

    if not pak_files:
        log(f"No .pak files found in {assets_dir}")
        return catalog

    log(f"Scanning {len(pak_files)} pak files...")

    for i, pak_path in enumerate(pak_files):
        if stop_check and stop_check():
            log("Scan aborted.")
            break

        try:
            data = pak_path.read_bytes()
        except Exception as e:
            log(f"  Could not read {pak_path.name}: {e}")
            continue

        # Parse central directory without creating a full PakExtractor (no oodle needed for scanning)
        try:
            from nwextractor.pak.extractor import PakExtractor
            # Use a lightweight approach: just parse the directory
            extractor = PakExtractor.__new__(PakExtractor)
            entries = extractor._read_central_directory(data)
        except Exception as e:
            log(f"  Could not parse {pak_path.name}: {e}")
            continue

        file_count = 0
        for entry in entries:
            if entry.is_directory:
                continue

            category, sub_type = _classify(entry.path)

            fe = FileEntry(
                path=entry.path,
                pak_file=str(pak_path),
                compressed_size=entry.compressed_size,
                uncompressed_size=entry.uncompressed_size,
                category=category,
                sub_type=sub_type,
            )
            catalog.all_files.append(fe)

            # Add to category
            if category not in catalog.categories:
                catalog.categories[category] = CategoryInfo(name=category)
            cat = catalog.categories[category]

            if sub_type not in cat.sub_types:
                cat.sub_types[sub_type] = SubTypeInfo(name=sub_type)
            cat.sub_types[sub_type].files.append(fe)

            file_count += 1

        if file_count > 0:
            log(f"  {pak_path.name}: {file_count} files")

    # Sort categories by name, but put "Other" last
    sorted_cats = dict(sorted(
        catalog.categories.items(),
        key=lambda x: (x[0] == "Other", x[0]),
    ))
    catalog.categories = sorted_cats

    # Build directory tree for content browsing
    log("Building content tree...")
    catalog.dir_tree = build_directory_tree(catalog.all_files)

    log(f"\nScan complete: {catalog.total_files} files in {catalog.pak_count} paks")
    return catalog
