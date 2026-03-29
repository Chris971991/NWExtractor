"""Terrain data converters: surfacemap, distribution, vegetation, regionmat.

Surface Maps (.surfacemap):
  Header (84 bytes): format info + material names (newline-separated)
  Data: 512x512 RGB image where channels = material blend weights
  Output: PNG + JSON manifest with material names

Distribution Maps (.distribution):
  Binary format with length-prefixed vegetation category strings
  Output: JSON list of vegetation categories

Region Materials (.regionmat):
  XML format (Lumberyard ObjectStream) defining terrain material assignments
  Output: JSON via generic XML converter

Vegetation (.vegetation):
  Large binary vegetation instance placement data
  Output: Raw extraction (format too complex for simple conversion)
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image


def convert_surfacemap(src: Path, dst_dir: Path) -> Path | None:
    """Convert a .surfacemap to PNG + material manifest JSON."""
    data = src.read_bytes()
    if len(data) < 84:
        return None

    # Header: +4 = dimension, +8 = data_size, +16..84 = material names
    dim = struct.unpack_from("<I", data, 4)[0]
    data_size = struct.unpack_from("<I", data, 8)[0]
    header_size = len(data) - data_size

    if header_size < 16 or data_size == 0:
        return None

    # Extract material names from header (newline-separated ASCII)
    mat_text = data[16:header_size].decode("ascii", errors="replace")
    materials = [m.strip() for m in mat_text.replace("\x00", "").split("\n") if m.strip()]

    # Determine image dimensions
    # data_size = W * H * channels. Try 512x512 RGB first
    w, h, channels = 512, 512, 3
    if data_size != w * h * channels:
        # Try dim x dim
        if data_size == dim * dim * 3:
            w, h = dim, dim
        elif data_size == dim * dim:
            w, h, channels = dim, dim, 1
        else:
            return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Save as PNG
    pixel_data = np.frombuffer(data[header_size:header_size + data_size], dtype=np.uint8)
    if channels == 3:
        pixel_data = pixel_data.reshape(h, w, 3)
    else:
        pixel_data = pixel_data.reshape(h, w)

    png_path = dst_dir / src.with_suffix(".png").name
    Image.fromarray(pixel_data).save(str(png_path))

    # Save material manifest
    json_path = dst_dir / src.with_suffix(".materials.json").name
    manifest = {
        "source": src.name,
        "dimensions": [w, h],
        "channels": channels,
        "materials": materials,
    }
    json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return png_path


def convert_distribution(src: Path, dst_dir: Path) -> Path | None:
    """Convert a .distribution to JSON with vegetation categories."""
    data = src.read_bytes()
    if len(data) < 4:
        return None

    # Parse length-prefixed strings
    categories = []
    offset = 0
    while offset < len(data):
        # Look for length byte followed by readable ASCII
        remaining = len(data) - offset
        if remaining < 2:
            break

        # Try reading a length byte
        length = data[offset]
        if length == 0:
            offset += 1
            continue

        if offset + 1 + length <= len(data):
            candidate = data[offset + 1:offset + 1 + length]
            # Check if it's readable ASCII
            if all(32 <= b < 127 for b in candidate):
                categories.append(candidate.decode("ascii"))
                offset += 1 + length
                continue

        offset += 1

    if not categories:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    json_path = dst_dir / src.with_suffix(".json").name

    json_data = {
        "source": src.name,
        "category_count": len(categories),
        "categories": categories,
    }
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    return json_path
