"""Oodle decompression via ctypes.

New World uses Oodle (Kraken) compression for files within .pak archives.
The oo2core_8_win64.dll ships with the game and must be provided at runtime.
"""

import ctypes
from pathlib import Path


class OodleDecompressor:
    """Wrapper around oo2core_8_win64.dll for Oodle decompression."""

    def __init__(self, dll_path: Path):
        dll_path = Path(dll_path)
        if not dll_path.exists():
            raise FileNotFoundError(f"Oodle DLL not found: {dll_path}")

        try:
            self._lib = ctypes.cdll.LoadLibrary(str(dll_path))
        except OSError as e:
            raise RuntimeError(f"Failed to load Oodle DLL (requires 64-bit Windows + 64-bit Python): {e}") from e

        # OodleLZ_Decompress signature:
        #   int OodleLZ_Decompress(
        #       const void* compBuf, int compLen,
        #       void* decompBuf, int decompLen,
        #       int fuzzSafe, int checkCRC, int verbosity,
        #       void* decBufBase, int decBufSize,
        #       void* fpCallback, void* callbackUserData,
        #       void* decoderMemory, int decoderMemorySize,
        #       int threadPhase
        #   )
        self._decompress = self._lib.OodleLZ_Decompress
        self._decompress.restype = ctypes.c_int32

    def decompress(self, data: bytes, decompressed_size: int) -> bytes:
        """Decompress Oodle-compressed data.

        Args:
            data: Compressed bytes.
            decompressed_size: Expected size of decompressed output.

        Returns:
            Decompressed bytes.

        Raises:
            RuntimeError: If decompression fails.
        """
        output = ctypes.create_string_buffer(decompressed_size)
        result = self._decompress(
            ctypes.c_char_p(data),   # compBuf
            len(data),               # compLen
            output,                  # decompBuf
            decompressed_size,       # decompLen
            0,                       # fuzzSafe
            0,                       # checkCRC
            0,                       # verbosity
            None,                    # decBufBase
            None,                    # decBufSize (as pointer, None = 0)
            None,                    # fpCallback
            None,                    # callbackUserData
            None,                    # decoderMemory
            None,                    # decoderMemorySize (as pointer, None = 0)
            3,                       # threadPhase (3 = OodleLZ_Decode_ThreadPhaseAll)
        )
        if result <= 0:
            raise RuntimeError(f"Oodle decompression failed (returned {result})")
        return output.raw[:result]
