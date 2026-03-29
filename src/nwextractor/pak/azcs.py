"""Amazon Compressed Stream (AZCS) decompression.

Some files extracted from New World paks are wrapped in an AZCS container.
These have a 4-byte magic "AZCS", followed by a compressor ID and the
compressed payload.

Format:
  [4 bytes]  Signature: b"AZCS"
  [4 bytes]  CompressorID (big-endian uint32):
               0x73887d3a = ZLib  (crc32 of "zlib")
               0x72fd505e = ZStd  (crc32 of "zstd")
  [8 bytes]  UncompressedSize (big-endian uint64)
  [...]      Compressor-specific data

For ZLib:
  [4 bytes]  NumSeekPoints (big-endian uint32)
  [...]      ZLib compressed data
  [16 * N]   Seek point table (appended at end, stripped before decompression)
             Each seek point: 8 bytes compressed offset + 8 bytes uncompressed offset
"""

import struct
import zlib
from io import BytesIO

AZCS_SIGNATURE = b"AZCS"

COMPRESSOR_ZLIB = 0x73887D3A  # crc32("zlib")
COMPRESSOR_ZSTD = 0x72FD505E  # crc32("zstd")


def is_azcs(data: bytes) -> bool:
    """Check if data starts with the AZCS magic signature."""
    return data[:4] == AZCS_SIGNATURE


def decompress_azcs(data: bytes) -> bytes:
    """Decompress an AZCS-wrapped payload.

    Args:
        data: Raw bytes starting with AZCS signature.

    Returns:
        Decompressed bytes.

    Raises:
        ValueError: If signature is invalid or compressor is unsupported.
    """
    if not is_azcs(data):
        raise ValueError(f"Not an AZCS stream (got {data[:4]!r})")

    # Parse header (all big-endian)
    compressor_id, uncompressed_size = struct.unpack_from(">IQ", data, 4)

    payload = data[16:]  # After 4 sig + 4 compressor + 8 size

    if compressor_id == COMPRESSOR_ZLIB:
        return _decompress_zlib(payload, uncompressed_size)
    elif compressor_id == COMPRESSOR_ZSTD:
        return _decompress_zstd(payload, uncompressed_size)
    else:
        raise ValueError(f"Unsupported AZCS compressor: 0x{compressor_id:08x}")


def _decompress_zlib(payload: bytes, uncompressed_size: int) -> bytes:
    """Decompress AZCS ZLib payload."""
    # First 4 bytes of payload = num_seek_points (big-endian)
    num_seek_points = struct.unpack_from(">I", payload, 0)[0]
    compressed_data = payload[4:]

    # Strip trailing seek point table (16 bytes per seek point)
    seek_table_size = num_seek_points * 16
    if seek_table_size > 0 and seek_table_size < len(compressed_data):
        compressed_data = compressed_data[:-seek_table_size]

    return zlib.decompress(compressed_data)


def _decompress_zstd(payload: bytes, uncompressed_size: int) -> bytes:
    """Decompress AZCS ZStd payload."""
    try:
        import zstandard as zstd
    except ImportError:
        raise RuntimeError(
            "ZStd decompression requires the 'zstandard' package. "
            "Install with: pip install zstandard"
        )

    decompressor = zstd.ZstdDecompressor()
    return decompressor.decompress(payload, max_output_size=uncompressed_size)
