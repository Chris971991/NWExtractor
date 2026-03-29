"""Wwise WEM audio conversion to WAV.

Uses vgmstream-cli.exe for decoding Wwise audio files.
Auto-downloads vgmstream if not found on the system.
"""

from __future__ import annotations

import io
import os
import subprocess
import zipfile
from pathlib import Path
from urllib.request import urlopen

VGMSTREAM_URL = "https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip"
VGMSTREAM_EXE = "vgmstream-cli.exe"


def _find_vgmstream() -> Path | None:
    """Find vgmstream-cli.exe on the system."""
    # Check common locations
    candidates = [
        Path.cwd() / VGMSTREAM_EXE,
        Path.cwd() / "vgmstream" / VGMSTREAM_EXE,
        Path(__file__).parent.parent.parent.parent / VGMSTREAM_EXE,
        Path(__file__).parent.parent.parent.parent / "vgmstream" / VGMSTREAM_EXE,
    ]
    for p in candidates:
        if p.exists():
            return p

    # Check PATH
    for dir_path in os.environ.get("PATH", "").split(os.pathsep):
        p = Path(dir_path) / VGMSTREAM_EXE
        if p.exists():
            return p

    return None


def _download_vgmstream(dst_dir: Path, log_fn=None) -> Path | None:
    """Download vgmstream-cli.exe from GitHub releases."""
    log = log_fn or print
    vgm_dir = dst_dir / "vgmstream"
    exe_path = vgm_dir / VGMSTREAM_EXE

    if exe_path.exists():
        return exe_path

    log("Downloading vgmstream for WEM audio conversion...")
    try:
        response = urlopen(VGMSTREAM_URL, timeout=30)
        zip_data = response.read()

        vgm_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for name in zf.namelist():
                if name.endswith(".exe") or name.endswith(".dll"):
                    zf.extract(name, vgm_dir)

        if exe_path.exists():
            log(f"vgmstream downloaded to {exe_path}")
            return exe_path
        else:
            # Might be in a subdirectory
            for p in vgm_dir.rglob(VGMSTREAM_EXE):
                return p

    except Exception as e:
        log(f"Failed to download vgmstream: {e}")

    return None


def convert_wem(src: Path, dst_dir: Path, vgmstream_path: Path | None = None) -> Path | None:
    """Convert a WEM audio file to WAV using vgmstream-cli.

    Args:
        src: Source .wem file.
        dst_dir: Output directory.
        vgmstream_path: Path to vgmstream-cli.exe (auto-found if None).

    Returns:
        Path to converted WAV file, or None on failure.
    """
    if not src.exists():
        return None

    if vgmstream_path is None:
        vgmstream_path = _find_vgmstream()

    if vgmstream_path is None:
        return None

    dst_dir.mkdir(parents=True, exist_ok=True)
    out_path = dst_dir / src.with_suffix(".wav").name

    try:
        result = subprocess.run(
            [str(vgmstream_path), "-o", str(out_path), str(src)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and out_path.exists():
            return out_path
    except Exception:
        pass

    return None
