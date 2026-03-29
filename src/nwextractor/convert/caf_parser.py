"""CryEngine/Lumberyard CAF animation file parser.

CAF files use the same CrCh container as CGF files but contain:
  - MotionParameters chunk (0x3002): timing info (fps, frame count)
  - Controller chunks (0x100D): per-bone keyframe data

Controller v0x0831 layout after 20-byte header:
  [rot_data] [rot_times] [pos_data] [pos_times]

Rotation formats:
  0 = NoCompressQuat (16 bytes: 4 floats)
  8 = SmallTree64BitExtQuat (8 bytes: compressed 64-bit)

Position formats:
  0 = NoCompress (implied constant)
  2 = NoCompressVec3 (12 bytes: 3 floats)

Time formats:
  0 = None (constant/implied)
  1 = uint16 frame index
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path


CHUNK_CONTROLLER = 0x100D
CHUNK_MOTION_PARAMS = 0x3002
CHUNK_TIMING = 0x100E
CHUNK_GLOBAL_ANIM_HEADER = 0x3007

# Rotation format constants
ROT_NO_COMPRESS = 0       # 4 floats (x, y, z, w) = 16 bytes
ROT_SMALLTREE_48 = 5      # 48-bit compressed
ROT_SMALLTREE_64 = 6      # 64-bit compressed
ROT_SMALLTREE_64_EXT = 8  # 64-bit extended compressed

# Position format constants
POS_NONE = 0              # No position data
POS_NO_COMPRESS = 2       # 3 floats (x, y, z) = 12 bytes

# Time format constants
TIME_NONE = 0             # Constant interval
TIME_UINT16 = 1           # uint16 frame index

# Bytes per key for each format
ROT_KEY_SIZE = {0: 16, 5: 6, 6: 8, 8: 8}
POS_KEY_SIZE = {0: 0, 2: 12}


@dataclass
class Quat:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0


@dataclass
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class AnimKey:
    time: float = 0.0  # Time in seconds
    frame: int = 0     # Frame index


@dataclass
class RotationKey(AnimKey):
    rotation: Quat = field(default_factory=Quat)


@dataclass
class PositionKey(AnimKey):
    position: Vec3 = field(default_factory=Vec3)


@dataclass
class BoneTrack:
    """Animation track for a single bone."""
    controller_id: int = 0
    rotation_keys: list[RotationKey] = field(default_factory=list)
    position_keys: list[PositionKey] = field(default_factory=list)


@dataclass
class CafAnimation:
    """Parsed CAF animation file."""
    file_path: str = ""
    duration: float = 0.0       # Duration in seconds
    fps: float = 30.0           # Frames per second
    num_frames: int = 0         # Total frame count
    tracks: list[BoneTrack] = field(default_factory=list)


class CafParser:
    """Parse CryEngine CAF animation files."""

    def __init__(self, data: bytes):
        self._data = data

    @classmethod
    def from_file(cls, path: Path) -> CafAnimation:
        data = path.read_bytes()
        parser = cls(data)
        return parser.parse(str(path))

    def parse(self, file_path: str = "") -> CafAnimation:
        anim = CafAnimation(file_path=file_path)

        sig = self._data[:4]
        if sig != b"CrCh":
            raise ValueError(f"Not a CrCh file: {sig!r}")

        num_chunks = struct.unpack_from("<I", self._data, 8)[0]
        table_off = struct.unpack_from("<I", self._data, 12)[0]

        chunks = []
        for i in range(num_chunks):
            pos = table_off + i * 16
            chunks.append({
                "type": struct.unpack_from("<H", self._data, pos)[0],
                "ver": struct.unpack_from("<H", self._data, pos + 2)[0],
                "id": struct.unpack_from("<I", self._data, pos + 4)[0],
                "size": struct.unpack_from("<I", self._data, pos + 8)[0],
                "offset": struct.unpack_from("<I", self._data, pos + 12)[0],
            })

        # Parse MotionParameters
        for c in chunks:
            if c["type"] == CHUNK_MOTION_PARAMS:
                self._parse_motion_params(c, anim)

        # Parse Controllers
        for c in chunks:
            if c["type"] == CHUNK_CONTROLLER:
                track = self._parse_controller(c, anim)
                if track:
                    anim.tracks.append(track)

        return anim

    def _u16(self, off: int) -> int:
        return struct.unpack_from("<H", self._data, off)[0]

    def _u32(self, off: int) -> int:
        return struct.unpack_from("<I", self._data, off)[0]

    def _i32(self, off: int) -> int:
        return struct.unpack_from("<i", self._data, off)[0]

    def _f32(self, off: int) -> float:
        return struct.unpack_from("<f", self._data, off)[0]

    def _parse_motion_params(self, chunk: dict, anim: CafAnimation):
        off = chunk["offset"]
        if chunk["ver"] == 0x0925:
            # +12: frame duration (seconds per frame)
            # +20: total frames
            frame_duration = self._f32(off + 12)
            total_frames = self._i32(off + 20)
            if frame_duration > 0:
                anim.fps = 1.0 / frame_duration
            anim.num_frames = total_frames
            anim.duration = total_frames * frame_duration

    def _parse_controller(self, chunk: dict, anim: CafAnimation) -> BoneTrack | None:
        off = chunk["offset"]

        if chunk["ver"] != 0x0831:
            return None

        # Controller v0x0831 header (20 bytes)
        controller_id = self._u32(off)
        flags = self._u32(off + 4)
        num_rot = self._u16(off + 8)
        num_pos = self._u16(off + 10)
        rot_fmt = self._data[off + 12]
        rot_time_fmt = self._data[off + 13]
        pos_fmt = self._data[off + 14]
        pos_keys_info = self._data[off + 15]
        pos_time_fmt = self._data[off + 16]
        tracks_aligned = self._data[off + 17]

        track = BoneTrack(controller_id=controller_id)

        # Data starts after 20-byte header
        data_off = off + 20

        rot_key_size = ROT_KEY_SIZE.get(rot_fmt, 0)
        pos_key_size = POS_KEY_SIZE.get(pos_fmt, 0)

        if rot_key_size == 0 and num_rot > 0:
            return track  # Unsupported rotation format

        # Layout: [rot_data] [rot_times] [pos_data] [pos_times]
        cursor = data_off

        # Rotation data
        rot_data_start = cursor
        cursor += num_rot * rot_key_size
        # Align to 4 bytes
        if cursor % 4 != 0:
            cursor += 4 - (cursor % 4)

        # Rotation times
        rot_times_start = cursor
        if rot_time_fmt == TIME_UINT16:
            cursor += num_rot * 2
            if cursor % 4 != 0:
                cursor += 4 - (cursor % 4)

        # Position data
        pos_data_start = cursor
        cursor += num_pos * pos_key_size

        # Position times
        pos_times_start = cursor

        # Decode rotation keys
        fps = anim.fps if anim.fps > 0 else 30.0
        for i in range(num_rot):
            key = RotationKey()

            # Time
            if rot_time_fmt == TIME_UINT16:
                frame = self._u16(rot_times_start + i * 2)
                key.frame = frame
                key.time = frame / fps
            else:
                key.frame = i
                key.time = i / fps

            # Rotation
            key.rotation = self._decode_rotation(rot_data_start + i * rot_key_size, rot_fmt)
            track.rotation_keys.append(key)

        # Decode position keys
        for i in range(num_pos):
            key = PositionKey()

            if pos_time_fmt == TIME_UINT16:
                frame = self._u16(pos_times_start + i * 2)
                key.frame = frame
                key.time = frame / fps
            else:
                key.frame = i
                key.time = i / fps

            key.position = self._decode_position(pos_data_start + i * pos_key_size, pos_fmt)
            track.position_keys.append(key)

        return track

    def _decode_rotation(self, off: int, fmt: int) -> Quat:
        if fmt == ROT_NO_COMPRESS:
            x = self._f32(off)
            y = self._f32(off + 4)
            z = self._f32(off + 8)
            w = self._f32(off + 12)
            return Quat(x, y, z, w)

        elif fmt in (ROT_SMALLTREE_64, ROT_SMALLTREE_64_EXT):
            return self._decode_smalltree64(off)

        elif fmt == ROT_SMALLTREE_48:
            return self._decode_smalltree48(off)

        return Quat()  # Identity

    def _decode_smalltree64(self, off: int) -> Quat:
        """Decode 64-bit compressed quaternion.

        Packs 3 components in 21 bits each (signed, normalized to [-1,1])
        plus 1 bit for w sign. The 4th component is derived.
        """
        val = struct.unpack_from("<Q", self._data, off)[0]

        # Extract 21-bit components
        MASK_21 = (1 << 21) - 1
        c0 = val & MASK_21
        c1 = (val >> 21) & MASK_21
        c2 = (val >> 42) & MASK_21
        w_sign = (val >> 63) & 1

        # Convert from 21-bit unsigned to float [-sqrt(2)/2, sqrt(2)/2]
        SCALE = 1.0 / (1 << 20)  # Normalize to [0, ~2], then shift to [-1, 1]
        x = (c0 - (1 << 20)) * SCALE * 0.7071067811865476
        y = (c1 - (1 << 20)) * SCALE * 0.7071067811865476
        z = (c2 - (1 << 20)) * SCALE * 0.7071067811865476

        # Derive w
        w_sq = 1.0 - x * x - y * y - z * z
        w = math.sqrt(max(0.0, w_sq))
        if w_sign:
            w = -w

        # Normalize
        length = math.sqrt(x * x + y * y + z * z + w * w)
        if length > 0:
            x /= length
            y /= length
            z /= length
            w /= length

        return Quat(x, y, z, w)

    def _decode_smalltree48(self, off: int) -> Quat:
        """Decode 48-bit compressed quaternion (6 bytes)."""
        raw = struct.unpack_from("<HHH", self._data, off)
        SCALE = 1.0 / 32767.0

        x = (raw[0] - 32767) * SCALE
        y = (raw[1] - 32767) * SCALE
        z = (raw[2] - 32767) * SCALE

        w_sq = 1.0 - x * x - y * y - z * z
        w = math.sqrt(max(0.0, w_sq))

        return Quat(x, y, z, w)

    def _decode_position(self, off: int, fmt: int) -> Vec3:
        if fmt == POS_NO_COMPRESS:
            x = self._f32(off)
            y = self._f32(off + 4)
            z = self._f32(off + 8)
            return Vec3(x, y, z)

        return Vec3()
