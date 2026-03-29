"""DDS texture conversion to UE5-ready formats (PNG/TGA).

Pillow handles most DDS formats (BC1-BC7, DXT1/3/5, uncompressed).
Falls back to texconv.exe for anything Pillow can't open.

UE5 import notes:
  - PNG: best for diffuse/albedo, UI textures (lossless, supports alpha)
  - TGA: best for normal maps, masks (lossless, supports alpha, widely used in UE)
  - UE5 can import DDS directly for BC-compressed textures
"""

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import io
import struct

from PIL import Image


# DXGI SRGB → UNORM mappings. Pillow often can't open the SRGB variants,
# but the pixel data is identical — only the color space interpretation differs.
# Patching the format ID in the DX10 header lets Pillow decode them.
_SRGB_TO_UNORM = {
    29: 28,   # R8G8B8A8_UNORM_SRGB → R8G8B8A8_UNORM
    72: 71,   # BC1_UNORM_SRGB → BC1_UNORM
    75: 74,   # BC2_UNORM_SRGB → BC2_UNORM
    78: 77,   # BC3_UNORM_SRGB → BC3_UNORM
    92: 91,   # BC7_UNORM_SRGB → BC7_UNORM
}


def _open_dds_bytes(data: bytes) -> Image.Image:
    """Open DDS from bytes with Pillow, patching SRGB formats if needed."""
    data = bytearray(data)

    # Check for DX10 header and patch SRGB → UNORM if needed
    if len(data) >= 148:
        four_cc = data[84:88]
        if four_cc == b"DX10":
            dxgi_fmt = struct.unpack_from("<I", data, 128)[0]
            if dxgi_fmt in _SRGB_TO_UNORM:
                struct.pack_into("<I", data, 128, _SRGB_TO_UNORM[dxgi_fmt])

    img = Image.open(io.BytesIO(bytes(data)))
    img.load()  # Force full decode now
    return img


def _open_dds(path: Path) -> Image.Image:
    """Open a DDS file with Pillow, handling split mips and SRGB patching."""
    data = reassemble_dds(path)
    if data is None:
        data = path.read_bytes()
    return _open_dds_bytes(data)


# Default output format
FORMAT_PNG = "png"
FORMAT_TGA = "tga"
FORMAT_DDS = "dds"  # Pass-through (no conversion)

# File patterns that suggest normal maps (should use TGA for best UE5 compat)
NORMAL_MAP_HINTS = {"_n.", "_normal.", "_nrm.", "_ddna.", "_nm."}


def reassemble_dds(header_path: Path) -> bytes | None:
    """Reassemble a split DDS from header + mip files.

    CryEngine/Lumberyard splits DDS textures:
      .dds   = header only (format, dimensions, mip count)
      .dds.1 = smallest mip
      .dds.2 = next mip
      ...
      .dds.N = highest resolution mip

    The full DDS = header + mips concatenated from highest to lowest
    (.N, .N-1, ..., .1).
    """
    header = header_path.read_bytes()
    if len(header) < 128 or header[:4] != b"DDS ":
        return None

    # Find all mip files (.dds.1, .dds.2, etc.)
    parent = header_path.parent
    base_name = header_path.name  # e.g. "texture_diff.dds"
    mip_files = []
    for i in range(1, 20):  # Up to 20 mip levels
        mip_path = parent / f"{base_name}.{i}"
        if mip_path.exists():
            mip_files.append((i, mip_path))
        else:
            break

    if not mip_files:
        # No mip files — the DDS might be self-contained
        if len(header) > 512:
            return header
        return None

    # Also check for .dds.1a, .dds.2a etc. (alpha channel data)
    alpha_files = []
    for i in range(1, 20):
        alpha_path = parent / f"{base_name}.{i}a"
        if alpha_path.exists():
            alpha_files.append((i, alpha_path))
        else:
            break

    # Concatenate: header + mips from highest to lowest resolution
    parts = [header]
    for _, mip_path in reversed(mip_files):
        parts.append(mip_path.read_bytes())

    return b"".join(parts)


def convert_texture(
    src: Path,
    dst_dir: Path,
    output_format: str = FORMAT_PNG,
    auto_detect_normals: bool = True,
    texconv_path: Path | None = None,
) -> Path | None:
    """Convert a single DDS texture to PNG or TGA.

    Handles CryEngine split DDS files (header + .1/.2/.3 mip files).

    Args:
        src: Source DDS file path.
        dst_dir: Output directory (preserves relative structure).
        output_format: "png", "tga", or "dds" (pass-through).
        auto_detect_normals: If True, normal maps auto-export as TGA.
        texconv_path: Optional path to texconv.exe for fallback.

    Returns:
        Path to the converted file, or None if conversion failed.
    """
    if not src.exists():
        return None

    # Determine output format
    fmt = output_format
    if auto_detect_normals and fmt == FORMAT_PNG:
        name_lower = src.name.lower()
        if any(hint in name_lower for hint in NORMAL_MAP_HINTS):
            fmt = FORMAT_TGA

    # Pass-through for DDS
    if fmt == FORMAT_DDS:
        out_path = dst_dir / src.with_suffix(".dds").name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if src != out_path:
            shutil.copy2(src, out_path)
        return out_path

    out_path = dst_dir / src.with_suffix(f".{fmt}").name
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Reassemble split DDS (header + mip files) if needed
    dds_data = reassemble_dds(src)
    if dds_data is None:
        return None

    # Try Pillow
    try:
        img = _open_dds_bytes(dds_data)
        if img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA")
        img.save(out_path)
        return out_path
    except Exception:
        pass

    # Fallback to texconv.exe
    if texconv_path and texconv_path.exists():
        try:
            return _convert_with_texconv(src, out_path, fmt, texconv_path)
        except Exception:
            pass

    return None


def _convert_with_texconv(src: Path, out_path: Path, fmt: str, texconv_path: Path) -> Path | None:
    """Convert using Microsoft's texconv.exe (DirectXTex)."""
    out_dir = out_path.parent
    target_fmt = "png" if fmt == FORMAT_PNG else "tga"

    result = subprocess.run(
        [str(texconv_path), "-ft", target_fmt, "-o", str(out_dir), "-y", str(src)],
        capture_output=True, timeout=30,
    )
    if result.returncode == 0 and out_path.exists():
        return out_path
    return None


def batch_convert_textures(
    src_dir: Path,
    dst_dir: Path,
    output_format: str = FORMAT_PNG,
    auto_detect_normals: bool = True,
    texconv_path: Path | None = None,
    max_workers: int = 4,
    log_fn=None,
    stop_check=None,
    progress_fn=None,
) -> tuple[int, int]:
    """Convert all DDS textures in a directory tree.

    Args:
        src_dir: Root directory containing extracted DDS files.
        dst_dir: Output directory for converted textures.
        output_format: Default output format ("png", "tga", "dds").
        auto_detect_normals: Auto-detect normal maps and use TGA.
        texconv_path: Optional path to texconv.exe.
        max_workers: Number of parallel conversion threads.
        log_fn: Logging callback.
        stop_check: Callable returning True to abort.
        progress_fn: Callback(current, total) for progress updates.

    Returns:
        Tuple of (converted_count, error_count).
    """
    log = log_fn or (lambda msg: None)

    # Find all DDS files
    dds_files = sorted(src_dir.rglob("*.dds"))
    if not dds_files:
        log("No DDS files found.")
        return 0, 0

    total = len(dds_files)
    log(f"Converting {total:,} DDS textures to {output_format.upper()}...")

    converted = 0
    errors = 0

    def _convert_one(src_path: Path) -> bool:
        # Preserve directory structure relative to src_dir
        rel = src_path.parent.relative_to(src_dir)
        out_dir = dst_dir / rel
        result = convert_texture(
            src_path, out_dir,
            output_format=output_format,
            auto_detect_normals=auto_detect_normals,
            texconv_path=texconv_path,
        )
        return result is not None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for dds_path in dds_files:
            if stop_check and stop_check():
                break
            future = executor.submit(_convert_one, dds_path)
            futures[future] = dds_path

        for future in as_completed(futures):
            if stop_check and stop_check():
                executor.shutdown(wait=False, cancel_futures=True)
                break

            dds_path = futures[future]
            try:
                success = future.result()
                if success:
                    converted += 1
                else:
                    errors += 1
                    log(f"  FAIL: {dds_path.name}")
            except Exception as e:
                errors += 1
                log(f"  ERROR {dds_path.name}: {e}")

            if progress_fn:
                progress_fn(converted + errors, total)

    log(f"Texture conversion complete: {converted:,} converted, {errors} errors")
    return converted, errors
