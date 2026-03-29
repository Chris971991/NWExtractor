"""Game data converters: CDF character definitions, localization, datasheets.

CDF (Character Definition Files):
  XML defining which skeleton (.chr), skins (.skin), and attachments
  make up a character. Converts to JSON for UE5 blueprint setup.

Localization:
  XML string tables with game text for all languages.
  Converts to JSON key-value format for UE5 string tables.

Datasheets:
  Binary Lumberyard Object Stream format. Extracted as-is for now.
  Use new-world-tools datasheet-converter for JSON/CSV conversion.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


# ─── CDF (Character Definition) ───

@dataclass
class CharacterAttachment:
    name: str = ""
    attach_type: str = ""  # CA_SKIN, CA_BONE, CA_FACE, CA_PROX
    binding: str = ""       # Mesh file path
    bone_name: str = ""     # Bone to attach to
    material: str = ""
    flags: int = 0


@dataclass
class CharacterDefinition:
    name: str = ""
    skeleton: str = ""      # .chr file path
    skin: str = ""          # Primary .skin file
    material: str = ""
    attachments: list[CharacterAttachment] = field(default_factory=list)
    physics: str = ""


def parse_cdf(path: Path) -> CharacterDefinition | None:
    """Parse a CryEngine CDF (Character Definition File)."""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return None

    if root.tag != "CharacterDefinition":
        return None

    cdef = CharacterDefinition(name=path.stem)

    # Model (skeleton)
    model = root.find("Model")
    if model is not None:
        cdef.skeleton = model.get("File", "")
        cdef.material = model.get("Material", "")

    # Attachment list
    att_list = root.find("AttachmentList")
    if att_list is not None:
        for att_elem in att_list.findall("Attachment"):
            att = CharacterAttachment()
            att.name = att_elem.get("AName", "")
            att.attach_type = att_elem.get("Type", "")
            att.binding = att_elem.get("Binding", "")
            att.bone_name = att_elem.get("BoneName", "")
            att.material = att_elem.get("Material", "")
            att.flags = int(att_elem.get("Flags", "0"))
            cdef.attachments.append(att)

            # CA_SKIN type = this is a skin mesh
            if att.attach_type == "CA_SKIN" and not cdef.skin:
                cdef.skin = att.binding

    return cdef


def convert_cdf(src: Path, dst_dir: Path) -> Path | None:
    """Convert a CDF character definition to JSON."""
    cdef = parse_cdf(src)
    if cdef is None:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".character.json").name

    data = {
        "name": cdef.name,
        "skeleton": cdef.skeleton,
        "skin": cdef.skin,
        "material": cdef.material,
        "attachments": [
            {
                "name": a.name,
                "type": a.attach_type,
                "mesh": a.binding,
                "bone": a.bone_name,
                "material": a.material,
            }
            for a in cdef.attachments
        ],
    }

    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


# ─── Localization ───

def convert_localization(src: Path, dst_dir: Path) -> Path | None:
    """Convert a CryEngine localization XML to a JSON string table."""
    try:
        tree = ET.parse(src)
        root = tree.getroot()
    except Exception:
        return None

    if root.tag != "resources":
        return None

    strings = {}
    for elem in root.findall("string"):
        key = elem.get("key", "")
        text = elem.text or ""
        if key:
            entry = {"text": text}
            speaker = elem.get("speaker")
            if speaker:
                entry["speaker"] = speaker
            comment = elem.get("comment")
            if comment:
                entry["comment"] = comment
            strings[key] = entry

    if not strings:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".strings.json").name

    data = {
        "source_file": src.name,
        "string_count": len(strings),
        "strings": strings,
    }

    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
