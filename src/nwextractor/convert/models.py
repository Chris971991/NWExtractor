"""Model conversion: CGF/CGA/SKIN → OBJ or glTF/GLB.

- OBJ: simple static meshes (no skeleton)
- glTF/GLB: skeletal meshes with bone weights (UE5-ready)
"""

from pathlib import Path

from nwextractor.convert.cgf_parser import CgfFile, CgfParser, MeshData


def convert_model(src: Path, dst_dir: Path, output_format: str = "glb") -> Path | None:
    """Convert a CGF/CGA/SKIN file to OBJ or GLB.

    Args:
        src: Source .cgf/.cga/.skin file.
        dst_dir: Output directory.
        output_format: "glb" (default, with skeleton), "obj" (static only).

    Returns:
        Path to converted file, or None on failure.
    """
    try:
        cgf = CgfParser.from_file(src)
    except Exception:
        return None

    if not cgf.meshes:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)

    if output_format == "fbx":
        # Export GLB first, then convert to FBX via Blender
        from nwextractor.convert.gltf_export import export_glb
        from nwextractor.convert.fbx_convert import convert_glb_to_fbx, find_blender
        glb_path = dst_dir / src.with_suffix(".glb").name
        result = export_glb(cgf, glb_path)
        if result and find_blender():
            fbx_path = convert_glb_to_fbx(glb_path)
            if fbx_path:
                glb_path.unlink(missing_ok=True)  # Clean up intermediate GLB
                return fbx_path
        return result  # Fall back to GLB if Blender not available
    elif output_format == "glb":
        from nwextractor.convert.gltf_export import export_glb
        out_path = dst_dir / src.with_suffix(".glb").name
        return export_glb(cgf, out_path)
    elif output_format == "obj":
        return _export_obj(cgf, src, dst_dir)

    return None


def _export_obj(cgf: CgfFile, src: Path, dst_dir: Path) -> Path | None:
    """Export parsed CGF mesh to Wavefront OBJ format."""
    out_path = dst_dir / src.with_suffix(".obj").name
    mtl_path = dst_dir / (src.stem + "_material.mtl")

    lines = []
    lines.append(f"# Exported by NWExtractor from {src.name}")
    lines.append(f"mtllib {mtl_path.name}")
    lines.append("")

    vertex_offset = 0

    for mesh_idx, mesh in enumerate(cgf.meshes):
        if not mesh.vertices:
            continue

        obj_name = f"mesh_{mesh_idx}"
        lines.append(f"o {obj_name}")

        if cgf.material_name:
            lines.append(f"usemtl {cgf.material_name}")

        # Vertices (CryEngine is Z-up right-handed, same as OBJ)
        for v in mesh.vertices:
            lines.append(f"v {v.x:.6f} {v.y:.6f} {v.z:.6f}")

        # Normals
        has_normals = len(mesh.normals) == len(mesh.vertices)
        if has_normals:
            for n in mesh.normals:
                lines.append(f"vn {n.x:.6f} {n.y:.6f} {n.z:.6f}")

        # UVs (flip V for OBJ convention: OBJ uses bottom-left origin)
        has_uvs = len(mesh.uvs) == len(mesh.vertices)
        if has_uvs:
            for uv in mesh.uvs:
                lines.append(f"vt {uv.u:.6f} {1.0 - uv.v:.6f}")

        # Faces (triangles, 1-indexed in OBJ)
        lines.append("")
        for i in range(0, len(mesh.indices), 3):
            if i + 2 >= len(mesh.indices):
                break
            i0 = mesh.indices[i] + 1 + vertex_offset
            i1 = mesh.indices[i + 1] + 1 + vertex_offset
            i2 = mesh.indices[i + 2] + 1 + vertex_offset

            if has_uvs and has_normals:
                lines.append(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}")
            elif has_uvs:
                lines.append(f"f {i0}/{i0} {i1}/{i1} {i2}/{i2}")
            elif has_normals:
                lines.append(f"f {i0}//{i0} {i1}//{i1} {i2}//{i2}")
            else:
                lines.append(f"f {i0} {i1} {i2}")

        vertex_offset += len(mesh.vertices)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # Write basic MTL file
    mtl_lines = [
        f"# Material for {src.name}",
        f"newmtl {cgf.material_name or 'default'}",
        "Ka 0.2 0.2 0.2",
        "Kd 0.8 0.8 0.8",
        "Ks 0.1 0.1 0.1",
        "d 1.0",
    ]
    mtl_path.write_text("\n".join(mtl_lines), encoding="utf-8")

    return out_path


def batch_convert_models(
    src_dir: Path,
    dst_dir: Path,
    output_format: str = "obj",
    log_fn=None,
    stop_check=None,
    progress_fn=None,
) -> tuple[int, int]:
    """Convert all CGF/CGA/SKIN files in a directory tree."""
    log = log_fn or (lambda msg: None)

    model_files = []
    for ext in ("*.cgf", "*.cga", "*.skin"):
        model_files.extend(src_dir.rglob(ext))
    model_files.sort()

    if not model_files:
        log("No model files found.")
        return 0, 0

    total = len(model_files)
    log(f"Converting {total:,} models to {output_format.upper()}...")

    converted = 0
    errors = 0

    for i, src_path in enumerate(model_files):
        if stop_check and stop_check():
            break

        rel = src_path.parent.relative_to(src_dir)
        out_dir = dst_dir / rel

        try:
            result = convert_model(src_path, out_dir, output_format=output_format)
            if result:
                converted += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            log(f"  FAIL: {src_path.name}: {e}")

        if progress_fn:
            progress_fn(i + 1, total)

    log(f"Model conversion complete: {converted:,} converted, {errors} errors")
    return converted, errors


def convert_animation(src: Path, dst_dir: Path, output_format: str = "glb") -> Path | None:
    """Convert a CAF animation file to GLB or FBX with proper bone names.

    Searches for a matching skeleton (.skin/.chr) nearby to get the
    controller_id → bone_name mapping. This ensures the animation's bone
    names match the skeletal mesh for UE5 import.
    """
    from nwextractor.convert.caf_parser import CafParser
    from nwextractor.convert.gltf_export import export_animation_glb

    try:
        anim = CafParser.from_file(src)
    except Exception:
        return None

    if not anim.tracks:
        return None

    # Find matching skeleton to get bone names
    bone_name_map, bones = _find_skeleton_for_animation(src)

    dst_dir.mkdir(parents=True, exist_ok=True)
    glb_path = dst_dir / src.with_suffix(".glb").name
    result = export_animation_glb(anim, glb_path, bone_name_map=bone_name_map, bones=bones)

    if result and output_format == "fbx":
        from nwextractor.convert.fbx_convert import convert_glb_to_fbx, find_blender
        if find_blender():
            fbx_path = convert_glb_to_fbx(glb_path)
            if fbx_path:
                glb_path.unlink(missing_ok=True)
                return fbx_path

    return result


def _find_skeleton_for_animation(caf_path: Path) -> tuple[dict[int, str] | None, list | None]:
    """Search for a skeleton file near the animation to get bone name mapping.

    Looks for .skin/.chr files in the same directory, parent directories,
    or sibling directories to build a controller_id → bone_name map.
    """
    search_dirs = [
        caf_path.parent,
        caf_path.parent.parent,
    ]
    # Also check sibling directories
    if caf_path.parent.parent.exists():
        for sibling in caf_path.parent.parent.iterdir():
            if sibling.is_dir() and sibling != caf_path.parent:
                search_dirs.append(sibling)

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for ext in ("*.skin", "*.chr"):
            for skel_file in search_dir.glob(ext):
                try:
                    cgf = CgfParser.from_file(skel_file)
                    if cgf.bones:
                        bone_map = {b.controller_id: b.name for b in cgf.bones}
                        return bone_map, cgf.bones
                except Exception:
                    continue

    return None, None
