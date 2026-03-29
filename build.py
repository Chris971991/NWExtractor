"""Build NWExtractor as a standalone .exe using PyInstaller."""

import subprocess
import sys
from pathlib import Path

def build():
    root = Path(__file__).parent
    src = root / "src"

    # Find customtkinter for bundling its assets
    import customtkinter
    ctk_path = Path(customtkinter.__path__[0])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "NWExtractor",
        "--icon", "NONE",
        # Add customtkinter assets
        "--add-data", f"{ctk_path};customtkinter",
        # Hidden imports that PyInstaller might miss
        "--hidden-import", "pygltflib",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.DdsImagePlugin",
        "--hidden-import", "numpy",
        "--hidden-import", "tifffile",
        "--hidden-import", "imagecodecs",
        "--hidden-import", "zstandard",
        "--hidden-import", "nwextractor.convert.textures",
        "--hidden-import", "nwextractor.convert.models",
        "--hidden-import", "nwextractor.convert.cgf_parser",
        "--hidden-import", "nwextractor.convert.caf_parser",
        "--hidden-import", "nwextractor.convert.gltf_export",
        "--hidden-import", "nwextractor.convert.materials",
        "--hidden-import", "nwextractor.convert.heightmaps",
        "--hidden-import", "nwextractor.convert.levels",
        "--hidden-import", "nwextractor.convert.gamedata",
        "--hidden-import", "nwextractor.convert.datasheets",
        "--hidden-import", "nwextractor.convert.audio",
        "--hidden-import", "nwextractor.convert.terrain",
        "--hidden-import", "nwextractor.convert.az_deserialize",
        "--hidden-import", "nwextractor.convert.binary_formats",
        "--hidden-import", "nwextractor.convert.misc_formats",
        "--hidden-import", "nwextractor.updater",
        "--hidden-import", "nwextractor.pak.oodle",
        "--hidden-import", "nwextractor.pak.azcs",
        "--hidden-import", "nwextractor.pak.extractor",
        "--hidden-import", "nwextractor.pak.catalog",
        # Paths
        "--paths", str(src),
        # Entry point
        str(src / "nwextractor" / "gui.py"),
    ]

    print(f"Building NWExtractor.exe...")
    print(f"Command: {' '.join(cmd[:10])}...")

    result = subprocess.run(cmd, cwd=str(root))

    if result.returncode == 0:
        dist = root / "dist" / "NWExtractor"
        exe = dist / "NWExtractor.exe"
        if exe.exists():
            print(f"\nBuild successful!")
            print(f"  Output: {dist}")
            print(f"  Exe: {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
            print(f"\nTo distribute: zip the entire 'dist/NWExtractor' folder")
        else:
            print(f"\nBuild completed but exe not found at {exe}")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")


if __name__ == "__main__":
    build()
