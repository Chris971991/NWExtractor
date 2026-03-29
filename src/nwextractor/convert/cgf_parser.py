"""CryEngine/Lumberyard CGF/CGA/SKIN binary format parser.

File format (CrCh variant used by New World / Lumberyard):
  Header: "CrCh" (4) + version (u32) + num_chunks (u32) + chunk_table_offset (u32)
  Chunk table: num_chunks × 16-byte entries:
    type (u16) + version (u16) + id (u32) + offset (u32) + size (u32)
  Chunk data: referenced by offset from chunk table entries.

Chunk types (from CryHeaders.h):
  0x1000 = Mesh          0x100B = Node           0x1013 = SourceInfo
  0x1014 = MtlName       0x1015 = ExportFlags    0x1016 = DataStream
  0x1017 = MeshSubsets    0x1018 = MeshPhysicsData
  0x2000 = CompiledBones  0x2004 = CompiledIntFaces
  0x2005 = CompiledIntSkinVertices  0x2006 = CompiledExt2IntMap
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path


# ─── Chunk Type Constants ───

CHUNK_MESH = 0x1000
CHUNK_HELPER = 0x1001
CHUNK_BONE_ANIM = 0x1003
CHUNK_BONE_NAME_LIST = 0x1005
CHUNK_NODE = 0x100B
CHUNK_CONTROLLER = 0x100D
CHUNK_TIMING = 0x100E
CHUNK_MTL_NAME = 0x1014
CHUNK_EXPORT_FLAGS = 0x1015
CHUNK_DATA_STREAM = 0x1016
CHUNK_MESH_SUBSETS = 0x1017
CHUNK_MESH_PHYSICS = 0x1018
CHUNK_COMPILED_BONES = 0x2000
CHUNK_COMPILED_PHYS_BONES = 0x2001
CHUNK_COMPILED_MORPH_TARGETS = 0x2002
CHUNK_COMPILED_INT_FACES = 0x2004
CHUNK_COMPILED_INT_SKIN_VERTS = 0x2005
CHUNK_COMPILED_EXT2INT_MAP = 0x2006
CHUNK_BONES_BOXES = 0x3004

# Stream type constants
STREAM_POSITIONS = 0
STREAM_NORMALS = 1
STREAM_TEXCOORDS = 2
STREAM_COLORS = 3
STREAM_COLORS2 = 4
STREAM_INDICES = 5
STREAM_TANGENTS = 6
STREAM_BONEMAPPING = 9
STREAM_QTANGENTS = 12
STREAM_P3S_C4B_T2S = 15

STREAM_NAMES = {
    0: "POSITIONS", 1: "NORMALS", 2: "TEXCOORDS", 3: "COLORS",
    4: "COLORS2", 5: "INDICES", 6: "TANGENTS", 9: "BONEMAPPING",
    12: "QTANGENTS", 15: "P3S_C4B_T2S",
}


# ─── Data Classes ───

@dataclass
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class UV:
    u: float = 0.0
    v: float = 0.0


@dataclass
class ChunkTableEntry:
    chunk_type: int = 0
    version: int = 0
    chunk_id: int = 0
    offset: int = 0
    size: int = 0


@dataclass
class MeshSubset:
    first_index: int = 0
    num_indices: int = 0
    first_vertex: int = 0
    num_vertices: int = 0
    material_id: int = 0


@dataclass
class BoneWeight:
    """Per-vertex bone weights (up to 4 bones)."""
    bone_ids: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    weights: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])


@dataclass
class Bone:
    name: str = ""
    parent_index: int = -1
    position: Vec3 = field(default_factory=Vec3)
    rotation: tuple = (0.0, 0.0, 0.0, 1.0)  # quaternion (x, y, z, w)


@dataclass
class NodeData:
    name: str = ""
    object_id: int = -1
    parent_id: int = -1
    material_id: int = -1
    transform: list[list[float]] = field(default_factory=lambda: [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])


@dataclass
class MeshData:
    """Parsed mesh data from a CGF/SKIN file."""
    vertices: list[Vec3] = field(default_factory=list)
    normals: list[Vec3] = field(default_factory=list)
    uvs: list[UV] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    subsets: list[MeshSubset] = field(default_factory=list)
    bone_weights: list[BoneWeight] = field(default_factory=list)
    material_name: str = ""


@dataclass
class CgfFile:
    """Fully parsed CGF/CGA/SKIN file."""
    version: int = 0
    file_path: str = ""
    nodes: list[NodeData] = field(default_factory=list)
    meshes: list[MeshData] = field(default_factory=list)
    bones: list[Bone] = field(default_factory=list)
    material_name: str = ""


# ─── Parser ───

class CgfParser:
    """Parse CryEngine/Lumberyard CGF, CGA, and SKIN binary files."""

    def __init__(self, data: bytes):
        self._data = data
        self._chunks: list[ChunkTableEntry] = []
        self._chunks_by_id: dict[int, ChunkTableEntry] = {}

    @classmethod
    def from_file(cls, path: Path) -> CgfFile:
        data = path.read_bytes()
        parser = cls(data)
        return parser.parse(str(path))

    def parse(self, file_path: str = "") -> CgfFile:
        result = CgfFile(file_path=file_path)

        # Read header
        sig = self._data[:4]
        if sig == b"CrCh":
            result.version = self._u32(4)
            num_chunks = self._u32(8)
            table_offset = self._u32(12)
        elif sig == b"#ivo":
            result.version = self._u32(4)
            num_chunks = self._u32(8)
            table_offset = self._u32(12)
        else:
            raise ValueError(f"Unknown CGF signature: {sig!r}")

        # Read chunk table (16 bytes per entry)
        self._chunks = []
        for i in range(num_chunks):
            pos = table_offset + i * 16
            entry = ChunkTableEntry(
                chunk_type=self._u16(pos),
                version=self._u16(pos + 2),
                chunk_id=self._u32(pos + 4),
                size=self._u32(pos + 8),    # Size comes before offset in CrCh v0x746
                offset=self._u32(pos + 12),
            )
            self._chunks.append(entry)
            self._chunks_by_id[entry.chunk_id] = entry

        # Parse material name
        for c in self._by_type(CHUNK_MTL_NAME):
            result.material_name = self._parse_mtl_name(c)

        # Parse bones (SKIN/CHR files)
        for c in self._by_type(CHUNK_COMPILED_BONES):
            result.bones = self._parse_compiled_bones(c)

        # Parse mesh
        for c in self._by_type(CHUNK_MESH):
            mesh = self._parse_mesh(c)
            if mesh and mesh.vertices:
                mesh.material_name = result.material_name
                result.meshes.append(mesh)

        # Parse nodes
        for c in self._by_type(CHUNK_NODE):
            node = self._parse_node(c)
            if node:
                result.nodes.append(node)

        return result

    # ─── Chunk helpers ───

    def _by_type(self, chunk_type: int) -> list[ChunkTableEntry]:
        return [c for c in self._chunks if c.chunk_type == chunk_type]

    def _u8(self, offset: int) -> int:
        return self._data[offset]

    def _u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self._data, offset)[0]

    def _i32(self, offset: int) -> int:
        return struct.unpack_from("<i", self._data, offset)[0]

    def _u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self._data, offset)[0]

    def _f32(self, offset: int) -> float:
        return struct.unpack_from("<f", self._data, offset)[0]

    def _vec3(self, offset: int) -> Vec3:
        x, y, z = struct.unpack_from("<fff", self._data, offset)
        return Vec3(x, y, z)

    def _string(self, offset: int, max_len: int) -> str:
        raw = self._data[offset:offset + max_len]
        null = raw.find(0)
        if null >= 0:
            raw = raw[:null]
        return raw.decode("utf-8", errors="replace")

    # ─── Chunk parsers ───

    def _parse_mtl_name(self, chunk: ChunkTableEntry) -> str:
        off = chunk.offset
        # MtlName chunk: varies by version. The name is a null-terminated string.
        if chunk.version == 0x0804 or chunk.version == 0x0802:
            # Skip flags (4 bytes), then read name
            return self._string(off + 4, 128)
        elif chunk.version == 0x0800:
            return self._string(off, 128)
        else:
            return self._string(off, min(chunk.size, 128))

    def _parse_node(self, chunk: ChunkTableEntry) -> NodeData | None:
        off = chunk.offset
        node = NodeData()

        if chunk.version == 0x0824:
            node.name = self._string(off, 64)
            node.object_id = self._i32(off + 64)
            node.parent_id = self._i32(off + 68)
            # nChildren at off+72
            node.material_id = self._i32(off + 76)
            # Skip obsolete[4] at off+80
            # Transform 4x4 matrix at off+84
            node.transform = []
            for row in range(4):
                r = []
                for col in range(4):
                    r.append(self._f32(off + 84 + (row * 4 + col) * 4))
                node.transform.append(r)
        else:
            node.name = self._string(off, 64)

        return node

    def _parse_mesh(self, chunk: ChunkTableEntry) -> MeshData | None:
        off = chunk.offset
        mesh = MeshData()

        if chunk.version == 0x0802:
            n_flags = self._i32(off)
            n_flags2 = self._i32(off + 4)
            n_verts = self._i32(off + 8)
            n_indices = self._i32(off + 12)
            n_subsets = self._i32(off + 16)
            subsets_chunk_id = self._i32(off + 20)
            vert_anim_id = self._i32(off + 24)

            # Stream chunk IDs: [CGF_STREAM_NUM_TYPES (16)][8 slots] = 128 int32s
            # Each stream type has 8 possible slots; slot 0 is the primary one
            stream_ids = {}
            for stream_type in range(16):
                val = self._i32(off + 28 + stream_type * 32)  # slot 0 of each type
                if val != 0:
                    stream_ids[stream_type] = val

            # Parse subsets
            if subsets_chunk_id in self._chunks_by_id:
                mesh.subsets = self._parse_mesh_subsets(self._chunks_by_id[subsets_chunk_id])

            # Parse data streams
            for stream_type, chunk_id in stream_ids.items():
                if chunk_id not in self._chunks_by_id:
                    continue
                ds_chunk = self._chunks_by_id[chunk_id]
                self._parse_data_stream(ds_chunk, mesh)

        return mesh

    def _parse_mesh_subsets(self, chunk: ChunkTableEntry) -> list[MeshSubset]:
        off = chunk.offset
        subsets = []

        if chunk.version == 0x0800:
            # flags (4), nSubsets (4), reserved[2] (8) = 16 byte header
            n_subsets = self._i32(off + 4)
            entry_off = off + 16
            for i in range(n_subsets):
                s = MeshSubset(
                    first_index=self._i32(entry_off),
                    num_indices=self._i32(entry_off + 4),
                    first_vertex=self._i32(entry_off + 8),
                    num_vertices=self._i32(entry_off + 12),
                    material_id=self._i32(entry_off + 16),
                )
                subsets.append(s)
                entry_off += 36  # Each MeshSubset entry is 36 bytes (5 ints + 4 floats or padding)

        return subsets

    def _parse_data_stream(self, chunk: ChunkTableEntry, mesh: MeshData):
        """Parse a DataStream chunk and populate the mesh."""
        off = chunk.offset

        if chunk.version != 0x0801:
            return

        # STREAM_DATA_CHUNK_DESC_0801
        ds_flags = self._i32(off)
        ds_type = self._i32(off + 4)
        ds_index = self._i32(off + 8)
        ds_count = self._i32(off + 12)
        ds_elem_size = self._i32(off + 16)
        # reserved[2] at off+20
        data_start = off + 28

        if ds_type == STREAM_POSITIONS:
            for i in range(ds_count):
                mesh.vertices.append(self._vec3(data_start + i * ds_elem_size))

        elif ds_type == STREAM_NORMALS:
            if ds_elem_size == 12:  # 3 floats
                for i in range(ds_count):
                    mesh.normals.append(self._vec3(data_start + i * ds_elem_size))

        elif ds_type == STREAM_TEXCOORDS:
            if ds_elem_size == 8:  # 2 floats (u, v)
                for i in range(ds_count):
                    u = self._f32(data_start + i * 8)
                    v = self._f32(data_start + i * 8 + 4)
                    mesh.uvs.append(UV(u, v))

        elif ds_type == STREAM_INDICES:
            if ds_elem_size == 2:  # uint16
                for i in range(ds_count):
                    mesh.indices.append(self._u16(data_start + i * 2))
            elif ds_elem_size == 4:  # uint32
                for i in range(ds_count):
                    mesh.indices.append(self._u32(data_start + i * 4))

        elif ds_type == STREAM_TANGENTS:
            pass  # Skip tangents for now — can be recomputed

        elif ds_type == STREAM_BONEMAPPING:
            for i in range(ds_count):
                bw = BoneWeight()
                p = data_start + i * ds_elem_size
                if ds_elem_size >= 16:
                    # 4 bone IDs (uint16) + 4 weights (uint16 normalized)
                    # or 4 bone IDs (uint8) + 4 weights (uint8)
                    # Common format: 4× (uint16 bone_id, uint16 weight)
                    for j in range(4):
                        bw.bone_ids[j] = self._u16(p + j * 4)
                        bw.weights[j] = self._u16(p + j * 4 + 2) / 255.0
                elif ds_elem_size == 8:
                    # 4 bone IDs (uint8) + 4 weights (uint8)
                    for j in range(4):
                        bw.bone_ids[j] = self._u8(p + j)
                    for j in range(4):
                        bw.weights[j] = self._u8(p + 4 + j) / 255.0
                mesh.bone_weights.append(bw)

    def _parse_compiled_bones(self, chunk: ChunkTableEntry) -> list[Bone]:
        """Parse CompiledBones chunk (0x2000)."""
        off = chunk.offset
        bones = []

        if chunk.version == 0x0800:
            # Each bone entry in v0x0800 is typically 584 bytes
            # But let's calculate from chunk size
            # Bone format: controller_id(4) + physics(4*8=32) + geometry(4*8=32) +
            #   name (256) + parent_index(4) + num_children(4) + controller_id(4) +
            #   props(32) + phys_geometry...
            # Actually the exact size varies. Let's use a simpler approach:
            # Try 584-byte entries first, fall back to detection
            bone_sizes = [584, 588, 152, 156]
            bone_size = 0
            for bs in bone_sizes:
                if bs > 0 and chunk.size % bs == 0:
                    bone_size = bs
                    break

            if bone_size == 0:
                return bones

            n_bones = chunk.size // bone_size
            for i in range(n_bones):
                p = off + i * bone_size
                bone = Bone()
                # The controller ID is first, then comes physics info
                # Bone name is typically at a known offset within the entry
                # For 584-byte entries: name starts at offset 32
                if bone_size >= 584:
                    bone.name = self._string(p + 32, 256)
                    bone.parent_index = self._i32(p + 32 + 256)
                elif bone_size >= 152:
                    bone.name = self._string(p + 32, 64)
                    bone.parent_index = self._i32(p + 32 + 64)
                bones.append(bone)

        elif chunk.version == 0x0801 or chunk.version == 0x0900:
            # Newer bone format — try 152-byte entries
            if chunk.size >= 152:
                bone_size = 152
                if chunk.size % bone_size != 0:
                    bone_size = 156
                n_bones = chunk.size // bone_size if bone_size > 0 else 0
                for i in range(n_bones):
                    p = off + i * bone_size
                    bone = Bone()
                    bone.name = self._string(p + 32, 64)
                    bone.parent_index = self._i32(p + 32 + 64)
                    bones.append(bone)

        return bones
