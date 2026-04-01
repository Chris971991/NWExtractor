"""GLB to FBX conversion via Blender headless mode.

FBX is the industry standard for UE5/Blender animation workflows.
Since FBX is proprietary, we use Blender's built-in FBX exporter
by running Blender in headless mode (--background).

Auto-finds Blender on the system. If not found, GLB is still usable
in UE5 directly.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Blender Python script for GLB → FBX conversion
_BLENDER_SCRIPT = '''
import bpy
import sys

argv = sys.argv
argv = argv[argv.index("--") + 1:]
input_path = argv[0]
output_path = argv[1]

# Clear scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Import GLB
bpy.ops.import_scene.gltf(filepath=input_path)

# Export FBX
bpy.ops.export_scene.fbx(
    filepath=output_path,
    use_selection=False,
    apply_scale_options='FBX_SCALE_ALL',
    bake_anim=True,
    bake_anim_use_all_bones=True,
    bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=True,
    add_leaf_bones=False,
    primary_bone_axis='Y',
    secondary_bone_axis='X',
    axis_forward='-Z',
    axis_up='Y',
)
'''


def find_blender() -> Path | None:
    """Auto-find Blender executable on the system."""
    # Check PATH first
    for dir_path in os.environ.get("PATH", "").split(os.pathsep):
        for exe in ("blender.exe", "blender"):
            p = Path(dir_path) / exe
            if p.exists():
                return p

    # Common install locations (Windows)
    common_paths = [
        Path("C:/Program Files/Blender Foundation"),
        Path("C:/Program Files (x86)/Blender Foundation"),
        Path(os.path.expanduser("~/AppData/Roaming/Blender Foundation")),
    ]

    # Check Steam
    steam_common = Path("C:/Program Files (x86)/Steam/steamapps/common")
    if steam_common.exists():
        common_paths.append(steam_common)

    for base in common_paths:
        if not base.exists():
            continue
        for p in base.rglob("blender.exe"):
            return p

    return None


def convert_glb_to_fbx(glb_path: Path, fbx_path: Path | None = None,
                        blender_path: Path | None = None) -> Path | None:
    """Convert a GLB file to FBX using Blender headless mode.

    Args:
        glb_path: Input .glb file.
        fbx_path: Output .fbx file (default: same name with .fbx extension).
        blender_path: Path to Blender executable (auto-detected if None).

    Returns:
        Path to .fbx file on success, None on failure.
    """
    if not glb_path.exists():
        return None

    if blender_path is None:
        blender_path = find_blender()

    if blender_path is None:
        return None  # Blender not found

    if fbx_path is None:
        fbx_path = glb_path.with_suffix(".fbx")

    # Write the conversion script to a temp file
    import tempfile
    script_file = Path(tempfile.gettempdir()) / "nwextractor_glb2fbx.py"
    script_file.write_text(_BLENDER_SCRIPT)

    try:
        result = subprocess.run(
            [
                str(blender_path),
                "--background",
                "--python", str(script_file),
                "--",
                str(glb_path.absolute()),
                str(fbx_path.absolute()),
            ],
            capture_output=True, timeout=60,
            cwd=str(glb_path.parent),
        )

        if fbx_path.exists() and fbx_path.stat().st_size > 0:
            return fbx_path

    except (subprocess.TimeoutExpired, OSError):
        pass

    return None
