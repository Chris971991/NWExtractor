# NWExtractor

Extract and convert **New World** game assets for **Unreal Engine 5** import.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

## Features

- **Smart asset browser** — Scan all game pak files and browse by content: Characters, Weapons, Crafting, Armor, and more
- **Cascading filters** — Drill down with dropdowns: `Weapons → Melee → Swords → 2H` then filter by asset type (Models, Textures, Animations)
- **Free-text search** — Type "corrupted" or "dynasty" to instantly filter
- **Selective extraction** — Checkbox tree view lets you pick exactly what you want
- **DDS texture conversion** — Automatically reassembles split DDS mip files and converts to PNG/TGA
- **Normal map detection** — Auto-detects normal maps (`_ddna`, `_normal`, etc.) and exports as TGA
- **Oodle decompression** — Auto-finds Oodle DLL from your system (UE5, other Steam games)
- **Dark themed GUI** — Clean interface built with CustomTkinter

## Screenshots

*Coming soon*

## Installation

### Requirements

- **Python 3.10+** (64-bit)
- **Windows** (Oodle DLL is Windows-only)
- **New World** installed via Steam

### Install

```bash
git clone https://github.com/Chris971991/NWExtractor.git
cd NWExtractor
pip install -e .
```

### Run

```bash
# Launch the GUI
python -m nwextractor.gui

# Or via command line
nwextractor extract --game-dir "C:\path\to\New World" --output ./extracted
```

## How It Works

### 1. Scan
Point NWExtractor at your New World game directory. It reads all `.pak` file indexes (no extraction yet) and builds a browsable content tree.

### 2. Browse & Select
Use the cascading filter dropdowns to find what you need:

| Goal | Filters |
|---|---|
| Female character textures | `Characters → Player → Female` + Asset Type: `Textures` |
| All sword models | `Weapons → Melee → Swords` + Asset Type: `Models` |
| Dynasty zone props | `Crafting → Props` + Search: `dynasty` |
| Everything for great axes | `Weapons → Melee → Axes → 2H` + Asset Type: `All` |

The tree view below lets you check/uncheck individual folders for fine-grained control.

### 3. Extract
Hit **Extract These** and NWExtractor will:
1. Decompress files from pak archives (Oodle + Deflate)
2. Unwrap AZCS (Amazon Compressed Stream) containers
3. Reassemble split DDS textures (header + mip files scattered across paks)
4. Convert textures to PNG/TGA (with SRGB format patching)
5. Clean up intermediate files

## Oodle DLL

New World's pak files use **Oodle compression**. The Oodle DLL (`oo2core_9_win64.dll`) is proprietary and cannot be distributed with this tool.

NWExtractor **automatically searches** for it in:
1. The NWExtractor directory (if you manually place it there)
2. Other Steam games (many ship the DLL — e.g. Marathon, Warzone, Fortnite)
3. Unreal Engine installs (`C:\Program Files\Epic Games\...`)

If auto-detection fails, copy `oo2core_9_win64.dll` from any UE5-based game into the NWExtractor folder.

## Asset Types

| Type | Source Format | Output |
|---|---|---|
| Textures | `.dds` (split: `.dds` + `.dds.1` ... `.dds.N`) | PNG / TGA |
| Normal Maps | `.dds` (auto-detected by `_ddna`, `_normal` suffix) | TGA |
| Models | `.cgf`, `.cga`, `.skin`, `.chr` | GLB (glTF binary) or OBJ |
| Animations | `.caf`, `.anm` | *Coming soon — FBX* |
| Materials | `.mtl` (XML) | *Coming soon — UE5 JSON* |
| Audio | `.wem`, `.bnk` | Raw extraction |
| Heightmaps | `.heightmap` | Raw extraction |

## New World Folder Structure

NWExtractor understands the game's internal asset organization:

```
Characters → Player (Male/Female/Mounts), NPC
Weapons    → Melee (Swords, Axes, Hammers, Spears, Staffs, Shields, ...)
           → Magic (Gauntlets), Ranged (Bows, Rifles), Siege, Tools
Crafting   → Props (Furniture, Decor, Lighting, Housing, zone-specific)
           → Architecture (Living, Ruins, Defensive, Social structures)
Climax     → Boss/endgame content (Ships, Skins)
Nature     → Trees, Rock veins
Levels     → Dungeons, Arenas, Raids (via sharedassets)
```

## Tech Stack

- **Python** — Core language
- **CustomTkinter** — Modern dark-themed GUI
- **Pillow** — DDS texture decoding and PNG/TGA export
- **ctypes** — Oodle DLL integration
- **struct** — Binary format parsing (ZIP, DDS headers)

## Roadmap

- [x] Pak extraction with Oodle decompression
- [x] AZCS (Amazon Compressed Stream) unwrapping
- [x] GUI with smart content browser
- [x] DDS → PNG/TGA texture conversion (with split mip reassembly)
- [x] CGF/CGA/SKIN → OBJ model conversion (static meshes)
- [x] CGF/SKIN → GLB model conversion (skeletal meshes with bone weights)
- [ ] CAF → FBX animation conversion
- [ ] MTL → UE5 material instance generation
- [ ] Level/map entity placement export
- [ ] Heightmap conversion for UE5 Landscape

## Credits

Built with research from:
- [giniedp/nw-extract](https://github.com/giniedp/nw-extract) — Original NW extraction tool (archived)
- [new-world-tools](https://github.com/new-world-tools/new-world-tools) — Go-based extraction suite
- [Markemp/Cryengine-Converter](https://github.com/Markemp/Cryengine-Converter) — CryEngine format reference
- [MontagueM/NewWorldUnpacker](https://github.com/MontagueM/NewWorldUnpacker) — Oodle decompression reference

## License

MIT
