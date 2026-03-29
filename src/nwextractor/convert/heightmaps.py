"""Heightmap conversion for UE5 Landscape import.

New World heightmaps are LZW-compressed 16-bit TIFF files (2048x2048).
Organized by region: sharedassets/coatlicue/<world>/regions/r_+XX_+YY/region.heightmap

Output formats:
  - R16: Raw 16-bit little-endian heightmap (UE5 Landscape native format)
  - PNG: 16-bit grayscale PNG (also importable in UE5)
"""

from pathlib import Path

import numpy as np


def convert_heightmap(src: Path, dst_dir: Path, output_format: str = "r16") -> Path | None:
    """Convert a New World .heightmap (TIFF) to UE5-ready format.

    Args:
        src: Source .heightmap file.
        dst_dir: Output directory.
        output_format: "r16" (raw 16-bit) or "png" (16-bit grayscale).

    Returns:
        Path to converted file, or None on failure.
    """
    try:
        import tifffile
        img = tifffile.imread(str(src))
    except ImportError:
        # Fallback to Pillow (works for uncompressed TIFFs)
        from PIL import Image
        pil_img = Image.open(src)
        img = np.array(pil_img)
    except Exception:
        return None

    if img.ndim != 2:
        return None  # Not a 2D heightmap

    dst_dir.mkdir(parents=True, exist_ok=True)
    img_u16 = img.astype(np.uint16)

    if output_format == "r16":
        out_path = dst_dir / src.with_suffix(".r16").name
        out_path.write_bytes(img_u16.tobytes())
        return out_path

    elif output_format == "png":
        from PIL import Image as PILImage
        out_path = dst_dir / src.with_suffix(".png").name
        pil_img = PILImage.fromarray(img_u16)
        pil_img.save(str(out_path))
        return out_path

    return None
