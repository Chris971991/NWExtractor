"""Level entity placement parser and UE5 DataTable CSV exporter.

Parses Lumberyard ObjectStream XML (mission0.entities_xml) from level.pak
files and extracts entity placements with transforms.

Output: CSV compatible with UE5 DataTable import for bulk entity spawning.
"""

from __future__ import annotations

import csv
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EntityPlacement:
    """A single entity placement from the level data."""
    name: str = ""
    entity_id: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)  # Euler angles (degrees)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    components: list[str] = field(default_factory=list)
    mesh_asset: str = ""
    slice_asset: str = ""
    entity_type: str = ""  # Derived from components


@dataclass
class LevelData:
    """All entity placements from a level."""
    level_name: str = ""
    entities: list[EntityPlacement] = field(default_factory=list)


def parse_entities_xml(path: Path) -> LevelData:
    """Parse a mission0.entities_xml file from a level.pak."""
    content = path.read_text(errors="replace")
    root = ET.fromstring(content)

    level = LevelData(level_name=path.parent.name)

    _find_entities(root, level)

    return level


def _find_entities(elem: ET.Element, level: LevelData):
    """Recursively find AZ::Entity elements and extract placement data."""
    if elem.get("name") == "AZ::Entity":
        entity = _parse_entity(elem)
        if entity and entity.position != (0.0, 0.0, 0.0):
            level.entities.append(entity)

    for child in elem:
        _find_entities(child, level)


def _parse_entity(elem: ET.Element) -> EntityPlacement | None:
    """Parse a single AZ::Entity element."""
    entity = EntityPlacement()

    for child in elem:
        if child.get("field") == "Name":
            entity.name = child.get("value", "")
        elif child.get("field") == "Id":
            for sub in child:
                if sub.get("field") == "id":
                    entity.entity_id = sub.get("value", "")
        elif child.get("field") == "Components":
            _parse_components(child, entity)

    if not entity.name:
        return None

    # Derive entity type from components
    comp_names = set(entity.components)
    if "SkinnedMeshComponent" in comp_names or "MeshComponent" in comp_names:
        entity.entity_type = "Mesh"
    elif "LightComponent" in comp_names:
        entity.entity_type = "Light"
    elif "ParticleComponent" in comp_names:
        entity.entity_type = "Particle"
    elif "AudioPreloadComponent" in comp_names or "AudioProxyComponent" in comp_names:
        entity.entity_type = "Audio"
    elif "SequenceComponent" in comp_names:
        entity.entity_type = "Sequence"
    elif "WaterOceanComponent" in comp_names:
        entity.entity_type = "Water"
    elif "SliceComponent" in comp_names:
        entity.entity_type = "Slice"
    else:
        entity.entity_type = "Other"

    return entity


def _parse_components(components_elem: ET.Element, entity: EntityPlacement):
    """Parse entity components for transform, mesh refs, etc."""
    for comp in components_elem:
        comp_name = comp.get("name", "")
        if comp_name:
            entity.components.append(comp_name)

        # Scan all descendants for useful data
        for sub in comp.iter():
            # Transform matrix (3x3 rotation + 3 position)
            if sub.get("field") == "m_worldTM" and sub.get("value"):
                _parse_transform(sub.get("value"), entity)

            # Mesh asset references
            field_name = sub.get("field", "")
            value = sub.get("value", "")

            if field_name in ("MeshAsset", "Asset", "m_meshAsset"):
                if value and any(value.endswith(ext) for ext in (".cgf", ".skin", ".cga")):
                    entity.mesh_asset = value

            if field_name == "SliceAsset" and value.endswith(".dynamicslice"):
                entity.slice_asset = value


def _parse_transform(value: str, entity: EntityPlacement):
    """Parse a Lumberyard transform string into position + rotation.

    Format: 9 floats (3x3 rotation matrix) + 3 floats (position)
    Example: "-0.0 1.0 0.0 -1.0 -0.0 0.0 0.0 0.0 1.0 777.5 505.8 20.0"
    """
    try:
        vals = [float(v) for v in value.split()]
    except (ValueError, AttributeError):
        return

    if len(vals) < 12:
        return

    # Position is the last 3 values
    entity.position = (vals[9], vals[10], vals[11])

    # Extract Euler angles from rotation matrix (approximate)
    # Matrix is row-major: [r00 r01 r02 r10 r11 r12 r20 r21 r22]
    r00, r01, r02 = vals[0], vals[1], vals[2]
    r10, r11, r12 = vals[3], vals[4], vals[5]
    r20, r21, r22 = vals[6], vals[7], vals[8]

    # Extract scale from matrix column magnitudes
    sx = math.sqrt(r00**2 + r10**2 + r20**2)
    sy = math.sqrt(r01**2 + r11**2 + r21**2)
    sz = math.sqrt(r02**2 + r12**2 + r22**2)
    entity.scale = (round(sx, 4), round(sy, 4), round(sz, 4))

    # Normalize rotation matrix
    if sx > 0:
        r00 /= sx; r10 /= sx; r20 /= sx
    if sy > 0:
        r01 /= sy; r11 /= sy; r21 /= sy
    if sz > 0:
        r02 /= sz; r12 /= sz; r22 /= sz

    # Extract Euler angles (YXZ order, degrees)
    pitch = math.asin(max(-1, min(1, -r20)))
    if abs(r20) < 0.999:
        yaw = math.atan2(r10, r00)
        roll = math.atan2(r21, r22)
    else:
        yaw = math.atan2(-r01, r11)
        roll = 0

    entity.rotation = (
        round(math.degrees(pitch), 2),
        round(math.degrees(yaw), 2),
        round(math.degrees(roll), 2),
    )


def export_entities_csv(level: LevelData, out_path: Path) -> Path | None:
    """Export entity placements as UE5 DataTable-compatible CSV.

    The CSV can be imported into UE5 as a DataTable to spawn entities
    at the correct positions.
    """
    if not level.entities:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Name", "EntityType", "PosX", "PosY", "PosZ",
            "RotPitch", "RotYaw", "RotRoll",
            "ScaleX", "ScaleY", "ScaleZ",
            "MeshAsset", "SliceAsset", "Components",
        ])

        for e in level.entities:
            writer.writerow([
                e.name, e.entity_type,
                f"{e.position[0]:.4f}", f"{e.position[1]:.4f}", f"{e.position[2]:.4f}",
                f"{e.rotation[0]:.2f}", f"{e.rotation[1]:.2f}", f"{e.rotation[2]:.2f}",
                f"{e.scale[0]:.4f}", f"{e.scale[1]:.4f}", f"{e.scale[2]:.4f}",
                e.mesh_asset, e.slice_asset,
                "|".join(e.components),
            ])

    return out_path


def export_entities_json(level: LevelData, out_path: Path) -> Path | None:
    """Export entity placements as JSON."""
    if not level.entities:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "level": level.level_name,
        "entity_count": len(level.entities),
        "entities": [
            {
                "name": e.name,
                "type": e.entity_type,
                "position": list(e.position),
                "rotation": list(e.rotation),
                "scale": list(e.scale),
                "mesh": e.mesh_asset,
                "slice": e.slice_asset,
                "components": e.components,
            }
            for e in level.entities
        ],
    }

    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def convert_level_entities(src: Path, dst_dir: Path) -> Path | None:
    """Convert a mission0.entities_xml to CSV + JSON."""
    level = parse_entities_xml(src)
    if not level.entities:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    csv_path = dst_dir / src.with_suffix(".csv").name.replace(".entities_xml", "_entities")
    csv_result = export_entities_csv(level, csv_path)

    json_path = dst_dir / src.with_suffix(".json").name.replace(".entities_xml", "_entities")
    export_entities_json(level, json_path)

    return csv_result
