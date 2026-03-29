"""Converters for miscellaneous remaining game formats.

BNK: Wwise sound bank listing (sections, object counts)
RNR: Animation runtime data (header + structured data)
CGFHeap: Geometry heap metadata extraction
WaterQT: Water quadtree data
Chunks: Terrain mesh chunk listing
MusicSheetC: Compiled music sheet data
TIF tractmaps: Already standard TIFF, convert to PNG
"""

from __future__ import annotations

import json
import struct
from pathlib import Path


def convert_bnk(src: Path, dst_dir: Path) -> Path | None:
    """Convert a Wwise BNK sound bank to a JSON manifest listing its contents."""
    data = src.read_bytes()
    if len(data) < 16 or data[:4] != b"BKHD":
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Parse BKHD header
    header_size = struct.unpack_from("<I", data, 4)[0]
    bank_version = struct.unpack_from("<I", data, 8)[0]
    bank_id = struct.unpack_from("<I", data, 12)[0]

    # Scan for sections
    sections = []
    offset = 0
    while offset < len(data) - 8:
        tag = data[offset:offset + 4]
        if all(32 <= b < 127 for b in tag):
            sec_size = struct.unpack_from("<I", data, offset + 4)[0]
            tag_str = tag.decode("ascii")
            sections.append({"tag": tag_str, "offset": offset, "size": sec_size})
            offset += 8 + sec_size
        else:
            offset += 1

    # Count embedded sounds from DIDX section
    sound_count = 0
    for sec in sections:
        if sec["tag"] == "DIDX":
            sound_count = sec["size"] // 12  # Each DIDX entry is 12 bytes

    out_path = dst_dir / src.with_suffix(".bnk.json").name
    result = {
        "source": src.name,
        "format": "wwise_soundbank",
        "bank_version": bank_version,
        "bank_id": bank_id,
        "sections": sections,
        "embedded_sound_count": sound_count,
        "total_size": len(data),
    }
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_rnr(src: Path, dst_dir: Path) -> Path | None:
    """Convert RNR animation runtime data to JSON."""
    data = src.read_bytes()
    if len(data) < 16:
        return None

    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != 0x1234ABCD:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Parse header fields
    field_count = struct.unpack_from("<I", data, 4)[0]
    version = struct.unpack_from("<I", data, 8)[0]

    # Extract float data from body (animation keyframe data)
    floats = []
    for i in range(16, len(data) - 3, 4):
        f = struct.unpack_from("<f", data, i)[0]
        if -1e6 < f < 1e6:
            floats.append(round(f, 6))

    out_path = dst_dir / src.with_suffix(".rnr.json").name
    result = {
        "source": src.name,
        "format": "animation_runtime",
        "magic": f"{magic:#010x}",
        "field_count": field_count,
        "version": version,
        "data_values": len(floats),
        "values": floats[:5000],  # Cap for JSON size
    }
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_cgfheap(src: Path, dst_dir: Path) -> Path | None:
    """Convert CGFHeap geometry data to a JSON metadata manifest.

    CGFHeap files contain LOD mesh vertex/index buffer data.
    Full mesh reconstruction requires the parent CGF file.
    We extract metadata: buffer sizes, vertex counts, etc.
    """
    data = src.read_bytes()
    if len(data) < 8:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Parse header: sequence of u32 values that describe buffer layout
    header_vals = []
    for i in range(0, min(64, len(data)), 4):
        header_vals.append(struct.unpack_from("<I", data, i)[0])

    # Estimate vertex/index counts from data size
    # Typical vertex = 32 bytes (pos+normal+uv+tangent), index = 2 bytes
    data_size = len(data)

    out_path = dst_dir / src.with_suffix(".cgfheap.json").name
    result = {
        "source": src.name,
        "format": "geometry_heap",
        "data_size": data_size,
        "header_values": header_vals,
        "estimated_vertices_32bpv": data_size // 32,
        "estimated_indices_2bpi": data_size // 2,
    }
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_waterqt(src: Path, dst_dir: Path) -> Path | None:
    """Convert water quadtree data to JSON."""
    data = src.read_bytes()
    if len(data) < 8:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Extract float values (water volume positions/dimensions)
    values = []
    for i in range(0, len(data) - 3, 4):
        f = struct.unpack_from("<f", data, i)[0]
        if -100000 < f < 100000 and f != 0:
            values.append(round(f, 4))

    out_path = dst_dir / src.with_suffix(".water.json").name
    result = {
        "source": src.name,
        "format": "water_quadtree",
        "data_size": len(data),
        "float_values": values,
    }
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_chunks(src: Path, dst_dir: Path) -> Path | None:
    """Convert terrain mesh chunk data to JSON metadata."""
    data = src.read_bytes()
    if len(data) < 8:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    out_path = dst_dir / src.with_suffix(".chunks.json").name
    result = {
        "source": src.name,
        "format": "terrain_chunks",
        "data_size": len(data),
        "header": data[:32].hex(),
    }
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_musicsheetc(src: Path, dst_dir: Path) -> Path | None:
    """Convert compiled music sheet to JSON."""
    data = src.read_bytes()
    if len(data) < 4:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Extract any readable strings (instrument/track names)
    strings = []
    i = 0
    while i < len(data):
        if 32 <= data[i] < 127:
            end = i
            while end < len(data) and 32 <= data[end] < 127:
                end += 1
            s = data[i:end].decode("ascii")
            if len(s) >= 3:
                strings.append(s)
            i = end
        else:
            i += 1

    out_path = dst_dir / src.with_suffix(".music.json").name
    result = {
        "source": src.name,
        "format": "music_sheet",
        "data_size": len(data),
        "strings": strings,
    }
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_tractmap_tif(src: Path, dst_dir: Path) -> Path | None:
    """Convert a tractmap TIF to PNG (already standard TIFF, just re-save as PNG)."""
    try:
        from PIL import Image
        img = Image.open(src)
        dst_dir.mkdir(parents=True, exist_ok=True)
        out_path = dst_dir / src.with_suffix(".png").name
        img.save(str(out_path))
        return out_path
    except Exception:
        try:
            import tifffile
            import numpy as np
            arr = tifffile.imread(str(src))
            from PIL import Image as PILImage
            dst_dir.mkdir(parents=True, exist_ok=True)
            out_path = dst_dir / src.with_suffix(".png").name
            PILImage.fromarray(arr).save(str(out_path))
            return out_path
        except Exception:
            return None
