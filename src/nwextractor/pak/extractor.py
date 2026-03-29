"""Pak file reader and extractor.

New World .pak files are ZIP-format archives. Files within can be:
- Uncompressed (compression method 0, or bitflags 0x14 in version field)
- Oodle-compressed (bitflags 0x08 or 0x09 in version field)
- Deflate-compressed (standard ZIP compression method 8)

The ZIP structure:
  [Local File Header + file data] * N
  [Central Directory Entry] * N
  [End of Central Directory Record]

We read the Central Directory to get the file list, then extract each file
using its Local File Header offset.
"""

import struct
import fnmatch
from pathlib import Path

from nwextractor.pak.oodle import OodleDecompressor
from nwextractor.pak.azcs import is_azcs, decompress_azcs


# ZIP signatures
SIG_LOCAL_FILE = b"\x50\x4b\x03\x04"
SIG_CENTRAL_DIR = b"\x50\x4b\x01\x02"
SIG_END_CENTRAL_DIR = b"\x50\x4b\x05\x06"

# Compression methods
COMPRESS_NONE = 0
COMPRESS_DEFLATE = 8

# New World uses the version-made-by field to signal Oodle compression.
# Known bitflag values:
#   0x08, 0x09 = Oodle compressed
#   0x14       = stored (no compression)
OODLE_FLAGS = {0x08, 0x09}
STORED_FLAGS = {0x14}


class CentralDirEntry:
    """Parsed ZIP Central Directory entry."""

    __slots__ = ("path", "compressed_size", "uncompressed_size", "local_header_offset",
                 "compression_method", "version_made_by", "is_oodle")

    def __init__(self, data: bytes, offset: int):
        # Central directory file header (46 bytes fixed + variable)
        (sig, version_made_by, version_needed, flags, compression_method,
         mod_time, mod_date, crc32, compressed_size, uncompressed_size,
         name_len, extra_len, comment_len, disk_start, internal_attr,
         external_attr, local_header_offset) = struct.unpack_from("<4sHHHHHHIIIHHHHHII", data, offset)

        if sig != SIG_CENTRAL_DIR:
            raise ValueError(f"Invalid central directory signature at offset {offset}")

        name_start = offset + 46
        self.path = data[name_start:name_start + name_len].decode("utf-8", errors="replace")
        self.compressed_size = compressed_size
        self.uncompressed_size = uncompressed_size
        self.local_header_offset = local_header_offset
        self.compression_method = compression_method
        self.version_made_by = version_made_by

        # Determine if this entry uses Oodle compression.
        # New World encodes this in version_made_by low byte or flags.
        self.is_oodle = (version_made_by & 0xFF) in OODLE_FLAGS or (flags & 0xFF) in OODLE_FLAGS

    @property
    def total_size(self) -> int:
        """Total size of this central directory entry in bytes."""
        # Re-read name/extra/comment lengths for size calc
        return 46 + len(self.path.encode("utf-8"))  # Approximate; exact uses stored lengths

    @property
    def is_directory(self) -> bool:
        return self.path.endswith("/") and self.uncompressed_size == 0


class EndOfCentralDir:
    """Parsed End of Central Directory record."""

    __slots__ = ("num_entries", "central_dir_size", "central_dir_offset")

    def __init__(self, data: bytes, offset: int):
        (sig, disk_num, disk_start, num_entries_disk, num_entries,
         central_dir_size, central_dir_offset, comment_len) = struct.unpack_from("<4sHHHHIIH", data, offset)

        if sig != SIG_END_CENTRAL_DIR:
            raise ValueError(f"Invalid EOCD signature at offset {offset}")

        self.num_entries = num_entries
        self.central_dir_size = central_dir_size
        self.central_dir_offset = central_dir_offset


class PakExtractor:
    """Extracts files from New World .pak archives."""

    def __init__(self, oodle_dll: Path | None = None):
        self._oodle = None
        if oodle_dll and Path(oodle_dll).exists():
            try:
                self._oodle = OodleDecompressor(oodle_dll)
            except Exception:
                pass  # Oodle not available — will skip Oodle-compressed files

    def _find_eocd(self, data: bytes) -> int:
        """Find the End of Central Directory record (searches from end of file)."""
        # EOCD is at least 22 bytes, search backwards from end
        search_start = max(0, len(data) - 65557)  # Max comment = 65535
        idx = data.rfind(SIG_END_CENTRAL_DIR, search_start)
        if idx == -1:
            raise ValueError("Could not find End of Central Directory record")
        return idx

    def _read_central_directory(self, data: bytes) -> list[CentralDirEntry]:
        """Parse the central directory from pak data."""
        eocd_offset = self._find_eocd(data)
        eocd = EndOfCentralDir(data, eocd_offset)

        entries = []
        offset = eocd.central_dir_offset

        for _ in range(eocd.num_entries):
            if offset >= len(data):
                break

            # Read fixed part to get variable lengths
            if data[offset:offset + 4] != SIG_CENTRAL_DIR:
                break

            name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, offset + 28)
            entry = CentralDirEntry(data, offset)
            entries.append(entry)
            offset += 46 + name_len + extra_len + comment_len

        return entries

    def _extract_file_data(self, data: bytes, entry: CentralDirEntry) -> bytes:
        """Extract and decompress a single file from the pak."""
        offset = entry.local_header_offset

        # Validate local file header
        sig = data[offset:offset + 4]
        if sig != SIG_LOCAL_FILE:
            raise ValueError(f"Invalid local file header for {entry.path} at offset {offset}")

        # Local file header: 30 bytes fixed + name_len + extra_len
        name_len, extra_len = struct.unpack_from("<HH", data, offset + 26)
        file_data_offset = offset + 30 + name_len + extra_len

        # Read the compressed (or raw) file data
        compressed_data = data[file_data_offset:file_data_offset + entry.compressed_size]

        if entry.compressed_size == 0 and entry.uncompressed_size == 0:
            return b""

        # Determine decompression method
        if entry.is_oodle and entry.compressed_size != entry.uncompressed_size:
            if self._oodle is None:
                raise ValueError("Oodle-compressed file but no oo2core DLL available")
            return self._oodle.decompress(compressed_data, entry.uncompressed_size)
        elif entry.compression_method == COMPRESS_DEFLATE:
            import zlib
            return zlib.decompress(compressed_data, -15)  # Raw deflate (no header)
        elif entry.compressed_size == entry.uncompressed_size:
            return compressed_data  # Stored/uncompressed
        elif entry.compression_method == COMPRESS_NONE:
            return compressed_data
        else:
            raise ValueError(f"Unknown compression for {entry.path}: method={entry.compression_method}, "
                             f"version={entry.version_made_by}")

    def list_files(self, pak_path: Path, patterns: list[str] | None = None) -> list[CentralDirEntry]:
        """List files in a pak archive, optionally filtered by glob patterns."""
        data = pak_path.read_bytes()
        entries = self._read_central_directory(data)

        if patterns:
            entries = [e for e in entries if not e.is_directory and _matches_any(e.path, patterns)]
        else:
            entries = [e for e in entries if not e.is_directory]

        return entries

    def extract_pak(self, pak_path: Path, output_dir: Path, patterns: list[str] | None = None,
                    dry_run: bool = False, log_fn=None, stop_check=None) -> int:
        """Extract all (or filtered) files from a .pak archive.

        Args:
            pak_path: Path to the .pak file.
            output_dir: Directory to write extracted files.
            patterns: Optional list of glob patterns to filter (e.g. ["*.dds", "*.cgf"]).
            dry_run: If True, only list files without extracting.
            log_fn: Optional callback for log messages (defaults to print).
            stop_check: Optional callable returning True to abort extraction.

        Returns:
            Number of files extracted/listed.
        """
        log = log_fn or print
        data = pak_path.read_bytes()
        entries = self._read_central_directory(data)

        count = 0
        for entry in entries:
            if stop_check and stop_check():
                break
            if entry.is_directory:
                continue
            if patterns and not _matches_any(entry.path, patterns):
                continue

            if dry_run:
                size_kb = entry.uncompressed_size / 1024
                log(f"  {entry.path} ({size_kb:.1f} KB)")
                count += 1
                continue

            try:
                file_data = self._extract_file_data(data, entry)
                # Auto-unwrap AZCS containers
                if is_azcs(file_data):
                    file_data = decompress_azcs(file_data)
            except Exception as e:
                log(f"  SKIP {entry.path}: {e}")
                continue

            out_path = output_dir / entry.path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(file_data)
            count += 1

        return count


def _matches_any(path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any of the given glob patterns."""
    name = path.rsplit("/", 1)[-1] if "/" in path else path
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in patterns)
