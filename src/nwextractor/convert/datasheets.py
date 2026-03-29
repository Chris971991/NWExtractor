"""New World datasheet binary format decoder.

Datasheets are Lumberyard's binary data tables containing game data:
items, weapons, NPCs, loot tables, quests, status effects, etc.

Binary format:
  Header (64 bytes):
    +0:  u32 signature (typically 18)
    +4:  u32 crc32
    +8:  u32 type_name_offset (in body string pool)
    +12: u32 crc32
    +16: u32 unique_id_offset (in body string pool)
    +20: u32 flags/version
    +24: u32 body_size (string pool size)
    +28-55: reserved (zeros)
    +56: u32 body_file_offset (not always accurate, use file_size - body_size)
    +60: u32 body_crc32

  Meta header (28 bytes, offset 64-91):
    +64: u32 flags
    +68: u32 (related to column count)
    +72-91: reserved

  Column definitions (offset 92, 12 bytes each):
    crc32(4) + name_offset_in_body(4) + column_type(4)
    Column types: 1=String, 2=Number, 3=Boolean

  Row data (after columns, 8 bytes per cell):
    value_offset_in_body(4) + padding(4)

  Body (string pool at end of file, body_size bytes):
    Null-terminated strings referenced by offsets from column/row data
"""

from __future__ import annotations

import csv
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path


COLUMN_TYPE_STRING = 1
COLUMN_TYPE_NUMBER = 2
COLUMN_TYPE_BOOLEAN = 3
COLUMN_TYPE_NAMES = {1: "string", 2: "number", 3: "boolean"}


@dataclass
class DatasheetColumn:
    name: str = ""
    column_type: int = 0
    crc32: int = 0


@dataclass
class Datasheet:
    sheet_type: str = ""
    unique_id: str = ""
    columns: list[DatasheetColumn] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def parse_datasheet(data: bytes) -> Datasheet | None:
    """Parse a binary datasheet file."""
    if len(data) < 92:
        return None

    ds = Datasheet()

    # Header
    signature = struct.unpack_from("<I", data, 0)[0]
    if signature == 0:
        return None

    type_name_off = struct.unpack_from("<I", data, 8)[0]
    unique_id_off = struct.unpack_from("<I", data, 16)[0]
    body_size = struct.unpack_from("<I", data, 24)[0]

    if body_size == 0 or body_size > len(data):
        return None

    # Body (string pool) is at the end of the file
    body_start = len(data) - body_size

    # Read type and unique_id strings
    ds.sheet_type = _read_string(data, body_start + type_name_off)
    ds.unique_id = _read_string(data, body_start + unique_id_off)

    # Scan column definitions starting at offset 92
    # Each column: crc32(4) + name_offset(4) + type(4) = 12 bytes
    off = 92
    while off < body_start - 12:
        col_type = struct.unpack_from("<I", data, off + 8)[0]
        if col_type not in (1, 2, 3):
            break
        name_off = struct.unpack_from("<I", data, off + 4)[0]
        if name_off >= body_size:
            break

        col = DatasheetColumn()
        col.crc32 = struct.unpack_from("<I", data, off)[0]
        col.name = _read_string(data, body_start + name_off)
        col.column_type = col_type
        ds.columns.append(col)
        off += 12

    if not ds.columns:
        return None

    col_count = len(ds.columns)
    row_data_start = 92 + col_count * 12
    remaining = body_start - row_data_start

    # Each cell is 8 bytes (offset + padding)
    row_size = col_count * 8
    if row_size == 0:
        return None

    row_count = remaining // row_size

    # Read rows
    for r in range(row_count):
        row = []
        for c in range(col_count):
            cell_off = row_data_start + (r * col_count + c) * 8
            if cell_off + 4 > len(data):
                break
            val_off = struct.unpack_from("<I", data, cell_off)[0]
            value = _read_string(data, body_start + val_off)
            row.append(value)
        if len(row) == col_count:
            ds.rows.append(row)

    return ds


def _read_string(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(0, offset)
    if end < 0:
        end = min(offset + 1024, len(data))
    return data[offset:end].decode("utf-8", errors="replace")


def convert_datasheet(src: Path, dst_dir: Path) -> Path | None:
    """Convert a binary datasheet to JSON + CSV."""
    data = src.read_bytes()
    ds = parse_datasheet(data)
    if ds is None or not ds.columns:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    col_names = [c.name for c in ds.columns]

    # JSON
    json_path = dst_dir / src.with_suffix(".json").name
    json_data = {
        "type": ds.sheet_type,
        "unique_id": ds.unique_id,
        "columns": [{"name": c.name, "type": COLUMN_TYPE_NAMES.get(c.column_type, "unknown")}
                     for c in ds.columns],
        "row_count": len(ds.rows),
        "rows": [dict(zip(col_names, row)) for row in ds.rows],
    }
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # CSV
    csv_path = dst_dir / src.with_suffix(".csv").name
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(col_names)
        for row in ds.rows:
            writer.writerow(row)

    return json_path
