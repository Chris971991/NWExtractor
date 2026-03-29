"""Lumberyard AZ ObjectStream binary deserializer.

Decodes binary serialized data used by:
  .dynamicslice, .timeline, .cloth, .vshapec, .dynamicuicanvas, .vegetation

Binary format (from ObjectStream.cpp):
  Stream starts with version tag, then nested elements.

  Each element:
    flags (u8):
      bit 3: ST_BINARYFLAG_ELEMENT_HEADER (1=element start, 0=element end)
      bit 4: ST_BINARYFLAG_HAS_VALUE
      bit 5: ST_BINARYFLAG_EXTRA_SIZE_FIELD
      bit 6: ST_BINARYFLAG_HAS_NAME
      bit 7: ST_BINARYFLAG_HAS_VERSION
      bits 0-2: value size (0-7) or extra size field width

    If ELEMENT_HEADER:
      [name_crc (u32)] if HAS_NAME
      [version (u8)] if HAS_VERSION
      [type_uuid (16 bytes)] always
      [extra_size (1/2/4 bytes)] if HAS_VALUE and EXTRA_SIZE_FIELD
      [value_data (N bytes)] if HAS_VALUE

    If flags == 0: element end marker

Known UUIDs (from entities_xml analysis):
  {75651658-8663-478D-9090-2432DFCAFA44} = AZ::Entity
  {AFD304E4-1773-47C8-855A-8B622398934F} = SliceComponent
  {484AE67D-ABD0-4D9C-B2C8-9BB0EEC900E0} = GameTransformComponent
  {5D9958E9-9F1E-4985-B532-FFFDE75FEDFD} = Transform
  {6383F1D3-BB27-4E6B-A49A-6409B2059EAA} = EntityId
  {D6597933-47CD-4FC8-B911-63F3E2B0993A} = AZ::u64
  {A0CA880C-AFE4-43CB-926C-59AC48496112} = bool
  {03AAAB3F-5C47-5A66-9EBC-D5FA4DB353C9} = AZStd::string
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

# Flags
ST_BINARYFLAG_ELEMENT_HEADER = 1 << 3
ST_BINARYFLAG_HAS_VALUE = 1 << 4
ST_BINARYFLAG_EXTRA_SIZE_FIELD = 1 << 5
ST_BINARYFLAG_HAS_NAME = 1 << 6
ST_BINARYFLAG_HAS_VERSION = 1 << 7
ST_BINARY_VALUE_SIZE_MASK = 0x07

# Known UUID → class name mapping
KNOWN_UUIDS = {
    "75651658-8663-478d-9090-2432dfcafa44": "AZ::Entity",
    "afd304e4-1773-47c8-855a-8b622398934f": "SliceComponent",
    "484ae67d-abd0-4d9c-b2c8-9bb0eec900e0": "GameTransformComponent",
    "5d9958e9-9f1e-4985-b532-fffde75fedfd": "Transform",
    "6383f1d3-bb27-4e6b-a49a-6409b2059eaa": "EntityId",
    "d6597933-47cd-4fc8-b911-63f3e2b0993a": "AZ::u64",
    "a0ca880c-afe4-43cb-926c-59ac48496112": "bool",
    "03aaab3f-5c47-5a66-9ebc-d5fa4db353c9": "AZStd::string",
    "edfcb2cf-f75d-43be-b26b-f35821b29247": "AZ::Component",
    "0d23b755-6e8f-5c6c-b7c9-a352a55dc1df": "AZStd::vector",
}


def _format_uuid(data: bytes, offset: int) -> str:
    """Read 16 bytes and format as UUID string."""
    b = data[offset:offset + 16]
    if len(b) < 16:
        return ""
    return (f"{b[0:4].hex()}-{b[4:6].hex()}-{b[6:8].hex()}-"
            f"{b[8:10].hex()}-{b[10:16].hex()}")


def _try_decode_value(data: bytes, size: int) -> str | int | float | bool | None:
    """Try to interpret raw value bytes as a common type."""
    if size == 0:
        return None
    if size == 1:
        v = data[0]
        if v in (0, 1):
            return bool(v)
        return v
    if size == 4:
        # Try float first, then int
        fval = struct.unpack_from("<f", data, 0)[0]
        ival = struct.unpack_from("<i", data, 0)[0]
        if -1e10 < fval < 1e10 and fval != 0 and abs(fval) > 1e-10:
            return round(fval, 6)
        return ival
    if size == 8:
        return struct.unpack_from("<q", data, 0)[0]
    # Try as null-terminated string
    if all(32 <= b < 127 or b == 0 for b in data):
        null = data.find(0)
        s = data[:null].decode("ascii") if null >= 0 else data.decode("ascii", errors="replace")
        if s:
            return s
    return data.hex()


class AZDeserializer:
    """Deserialize Lumberyard AZ ObjectStream binary format."""

    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0
        self._depth = 0
        self._max_depth = 50

    def deserialize(self) -> dict | None:
        if len(self._data) < 4:
            return None

        # Header: u32 version + u8 stream_tag
        version = struct.unpack_from("<I", self._data, 0)[0]

        if version > 100:
            # Not a standard AZ ObjectStream
            return {"_format": "unknown_binary", "_size": len(self._data),
                    "_header": self._data[:20].hex()}

        # Skip version (4 bytes) + stream sub-version byte (1 byte)
        self._offset = 5

        root = {"_version": version, "_elements": []}

        try:
            while self._offset < len(self._data):
                elem = self._read_element()
                if elem is None:
                    break
                root["_elements"].append(elem)
        except (struct.error, IndexError):
            pass

        return root

    def _read_element(self) -> dict | None:
        if self._offset >= len(self._data):
            return None

        flags = self._data[self._offset]
        self._offset += 1

        # Element end marker
        if flags == 0:
            return None

        if not (flags & ST_BINARYFLAG_ELEMENT_HEADER):
            return None

        elem = {}

        # Name CRC
        if flags & ST_BINARYFLAG_HAS_NAME:
            if self._offset + 4 > len(self._data):
                return None
            name_crc = struct.unpack_from("<I", self._data, self._offset)[0]
            self._offset += 4
            elem["_name_crc"] = f"{name_crc:#010x}"

        # Version
        if flags & ST_BINARYFLAG_HAS_VERSION:
            if self._offset >= len(self._data):
                return None
            version = self._data[self._offset]
            self._offset += 1
            elem["_version"] = version

        # Type UUID (always 16 bytes)
        if self._offset + 16 > len(self._data):
            return None
        uuid_str = _format_uuid(self._data, self._offset)
        self._offset += 16

        class_name = KNOWN_UUIDS.get(uuid_str, None)
        elem["_type"] = class_name or uuid_str

        # Value data
        if flags & ST_BINARYFLAG_HAS_VALUE:
            value_size = flags & ST_BINARY_VALUE_SIZE_MASK

            if flags & ST_BINARYFLAG_EXTRA_SIZE_FIELD:
                # Extra size field: bits 0-2 indicate width (1, 2, or 4 bytes)
                size_width = value_size
                if size_width == 0:
                    size_width = 1
                if self._offset + size_width > len(self._data):
                    return elem

                if size_width == 1:
                    value_size = self._data[self._offset]
                elif size_width == 2:
                    value_size = struct.unpack_from("<H", self._data, self._offset)[0]
                elif size_width >= 4:
                    value_size = struct.unpack_from("<I", self._data, self._offset)[0]
                self._offset += size_width

            if value_size > 0 and self._offset + value_size <= len(self._data):
                raw = self._data[self._offset:self._offset + value_size]
                self._offset += value_size
                elem["_value"] = _try_decode_value(raw, value_size)
        else:
            # No value — has child elements
            if self._depth < self._max_depth:
                self._depth += 1
                children = []
                while self._offset < len(self._data):
                    child = self._read_element()
                    if child is None:
                        break
                    children.append(child)
                self._depth -= 1
                if children:
                    elem["_children"] = children

        return elem


def deserialize_az_binary(src: Path, dst_dir: Path) -> Path | None:
    """Deserialize a Lumberyard AZ binary file to JSON."""
    data = src.read_bytes()
    if len(data) < 4:
        return None

    deser = AZDeserializer(data)
    result = deser.deserialize()
    if result is None:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".json").name

    result["_source"] = src.name
    result["_size"] = len(data)

    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    return out_path
