"""CryEngine MTL material parser and UE5 material manifest generator.

CryEngine MTL files are XML containing:
  - Shader name and parameters
  - Texture map references (Diffuse, Normal/Bumpmap, Specular, etc.)
  - Surface properties (diffuse color, specular, opacity, shininess)

This module parses MTL files and generates JSON manifests that describe
UE5 material instances, including which textures to assign to which slots.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


# CryEngine texture map names → UE5 material input names
TEXTURE_MAP_MAPPING = {
    "Diffuse": "BaseColor",
    "Bumpmap": "Normal",
    "Normal": "Normal",
    "Specular": "Specular",
    "Environment": "Metallic",
    "Detail": "Detail",
    "Heightmap": "Height",
    "Opacity": "Opacity",
    "Decal": "Decal",
    "SubSurface": "SubSurface",
    "Custom": "Custom",
    "[1] Custom": "Custom2",
    "Emittance": "Emissive",
}


@dataclass
class TextureSlot:
    """A texture assignment in a material."""
    cry_map: str = ""         # CryEngine map name (Diffuse, Bumpmap, etc.)
    ue5_slot: str = ""        # UE5 slot name (BaseColor, Normal, etc.)
    file_path: str = ""       # Original file path in game assets
    converted_path: str = ""  # Path after conversion (PNG/TGA)
    tile_u: float = 1.0
    tile_v: float = 1.0


@dataclass
class MaterialData:
    """Parsed material data from a CryEngine MTL file."""
    name: str = ""
    shader: str = ""
    surface_type: str = ""
    diffuse_color: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0)
    specular_color: tuple[float, ...] = (0.0, 0.0, 0.0, 1.0)
    emissive_color: tuple[float, ...] = (0.0, 0.0, 0.0, 1.0)
    emissive_intensity: float = 0.0
    opacity: float = 1.0
    shininess: float = 10.0
    textures: list[TextureSlot] = field(default_factory=list)
    sub_materials: list[MaterialData] = field(default_factory=list)
    is_transparent: bool = False


def parse_mtl(path: Path) -> MaterialData | None:
    """Parse a CryEngine MTL XML file."""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        try:
            content = path.read_text(errors="replace")
            root = ET.fromstring(content)
        except Exception:
            return None

    if root.tag == "Material":
        return _parse_material_element(root, path.stem)
    return None


def _parse_material_element(elem: ET.Element, name: str = "") -> MaterialData:
    """Parse a single <Material> element."""
    mat = MaterialData()
    mat.name = name or elem.get("Name", "")
    mat.shader = elem.get("Shader", "")
    mat.surface_type = elem.get("SurfaceType", "")
    mat.opacity = float(elem.get("Opacity", "1.0"))
    mat.shininess = float(elem.get("Shininess", "10"))

    # Check if transparent
    shader_lower = mat.shader.lower()
    mat.is_transparent = "transp" in shader_lower or mat.opacity < 1.0

    # Parse colors (format: "r,g,b,a")
    mat.diffuse_color = _parse_color(elem.get("Diffuse", "1,1,1,1"))
    mat.specular_color = _parse_color(elem.get("Specular", "0,0,0,1"))

    # Emittance: "r,g,b,intensity" or "r,g,b"
    emittance = elem.get("Emittance", "0,0,0,0")
    parts = [float(x) for x in emittance.split(",")]
    if len(parts) >= 4:
        mat.emissive_color = tuple(parts[:3])
        mat.emissive_intensity = parts[3]
    elif len(parts) == 3:
        mat.emissive_color = tuple(parts)

    # Parse textures
    textures_elem = elem.find("Textures")
    if textures_elem is not None:
        for tex_elem in textures_elem.findall("Texture"):
            slot = TextureSlot()
            slot.cry_map = tex_elem.get("Map", "")
            slot.file_path = tex_elem.get("File", "")
            slot.ue5_slot = TEXTURE_MAP_MAPPING.get(slot.cry_map, slot.cry_map)

            # Parse tiling from TexMod
            tex_mod = tex_elem.find("TexMod")
            if tex_mod is not None:
                slot.tile_u = float(tex_mod.get("TileU", "1"))
                slot.tile_v = float(tex_mod.get("TileV", "1"))

            # Convert file path to expected converted filename
            if slot.file_path:
                p = Path(slot.file_path)
                if p.suffix.lower() == ".dds":
                    # Will be converted to PNG or TGA
                    if "ddna" in p.stem.lower() or "normal" in p.stem.lower():
                        slot.converted_path = str(p.with_suffix(".tga"))
                    else:
                        slot.converted_path = str(p.with_suffix(".png"))
                else:
                    slot.converted_path = slot.file_path

            mat.textures.append(slot)

    # Parse sub-materials
    sub_mats_elem = elem.find("SubMaterials")
    if sub_mats_elem is not None:
        for i, sub_elem in enumerate(sub_mats_elem.findall("Material")):
            sub_mat = _parse_material_element(sub_elem, f"{mat.name}_sub{i}")
            mat.sub_materials.append(sub_mat)

    return mat


def _parse_color(color_str: str) -> tuple[float, ...]:
    """Parse a CryEngine color string 'r,g,b,a' or 'r,g,b'."""
    try:
        parts = [float(x) for x in color_str.split(",")]
        if len(parts) == 3:
            return tuple(parts) + (1.0,)
        return tuple(parts[:4])
    except (ValueError, IndexError):
        return (1.0, 1.0, 1.0, 1.0)


def material_to_ue5_json(mat: MaterialData) -> dict:
    """Convert parsed material to a UE5-friendly JSON structure."""
    result = {
        "name": mat.name,
        "shader": mat.shader,
        "blend_mode": "Translucent" if mat.is_transparent else "Opaque",
        "properties": {
            "base_color": list(mat.diffuse_color[:3]),
            "specular": list(mat.specular_color[:3]),
            "roughness": max(0.0, 1.0 - (mat.shininess / 255.0)),  # Approximate
            "metallic": 0.0,
            "opacity": mat.opacity,
            "emissive_color": list(mat.emissive_color[:3]),
            "emissive_intensity": mat.emissive_intensity,
        },
        "textures": {},
    }

    for tex in mat.textures:
        if tex.ue5_slot and tex.converted_path:
            result["textures"][tex.ue5_slot] = {
                "file": tex.converted_path,
                "original": tex.file_path,
                "tile": [tex.tile_u, tex.tile_v],
            }

    if mat.sub_materials:
        result["sub_materials"] = [material_to_ue5_json(sub) for sub in mat.sub_materials]

    return result


def convert_material(src: Path, dst_dir: Path) -> Path | None:
    """Convert a CryEngine MTL file to a UE5 material JSON manifest.

    Args:
        src: Source .mtl file.
        dst_dir: Output directory.

    Returns:
        Path to generated JSON file, or None on failure.
    """
    mat = parse_mtl(src)
    if mat is None:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".material.json").name

    ue5_data = material_to_ue5_json(mat)
    out_path.write_text(json.dumps(ue5_data, indent=2), encoding="utf-8")

    return out_path
