"""Converters for remaining binary game data formats.

Cloth (.cloth): Physics simulation parameter arrays (floats)
Vegetation (.vegetation): Instance placement data (positions in world)
VShapec (.vshapec): Vegetation bounding shape vertices
"""

from __future__ import annotations

import json
import struct
from pathlib import Path


def convert_cloth(src: Path, dst_dir: Path) -> Path | None:
    """Convert cloth simulation data to JSON with float parameter arrays."""
    data = src.read_bytes()
    if len(data) < 16:
        return None

    # Extract meaningful float values
    params = []
    for i in range(0, len(data) - 3, 4):
        f = struct.unpack_from("<f", data, i)[0]
        if -1e6 < f < 1e6:
            params.append(round(f, 6))

    if not params:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".cloth.json").name

    result = {
        "source": src.name,
        "format": "cloth_simulation",
        "parameter_count": len(params),
        "parameters": params,
    }

    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_vegetation(src: Path, dst_dir: Path) -> Path | None:
    """Convert vegetation instance placement data to JSON.

    Vegetation files contain instance positions for foliage/tree placement.
    Header includes dimension and instance count info.
    """
    data = src.read_bytes()
    if len(data) < 40:
        return None

    # Header: first u32s contain metadata
    header_val = struct.unpack_from("<I", data, 0)[0]
    dimension = struct.unpack_from("<I", data, 4)[0]

    # Extract float triplets (position data) from the body
    # Scan for sequences of valid float3 positions
    positions = []
    offset = 8  # Skip header
    while offset + 12 <= len(data) and len(positions) < 500000:
        x = struct.unpack_from("<f", data, offset)[0]
        y = struct.unpack_from("<f", data, offset + 4)[0]
        z = struct.unpack_from("<f", data, offset + 8)[0]

        # Valid world coordinates (New World map is ~14km, so positions < 20000)
        if all(-20000 < v < 20000 for v in (x, y, z)):
            if any(v != 0 for v in (x, y, z)):
                positions.append([round(x, 4), round(y, 4), round(z, 4)])

        offset += 4  # Slide by 4 bytes to find all positions

    if not positions:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".vegetation.json").name

    result = {
        "source": src.name,
        "format": "vegetation_placement",
        "dimension": dimension,
        "instance_count": len(positions),
        "positions": positions[:10000],  # Cap at 10K for JSON size
        "total_positions": len(positions),
    }

    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


def convert_vshapec(src: Path, dst_dir: Path) -> Path | None:
    """Convert vegetation shape (bounding volume) data to JSON."""
    data = src.read_bytes()
    if len(data) < 12:
        return None

    # Extract float3 vertices (bounding shape)
    header_size = 8  # Skip header bytes
    vertices = []
    offset = header_size
    while offset + 12 <= len(data):
        x = struct.unpack_from("<f", data, offset)[0]
        y = struct.unpack_from("<f", data, offset + 4)[0]
        z = struct.unpack_from("<f", data, offset + 8)[0]

        if all(-100000 < v < 100000 for v in (x, y, z)):
            if any(v != 0 for v in (x, y, z)):
                vertices.append([round(x, 4), round(y, 4), round(z, 4)])

        offset += 12  # Stride by float3

    if not vertices:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".shape.json").name

    result = {
        "source": src.name,
        "format": "vegetation_shape",
        "vertex_count": len(vertices),
        "vertices": vertices,
    }

    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path
