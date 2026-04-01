"""Export parsed CGF meshes and CAF animations to glTF 2.0 (.glb binary format).

glTF supports:
  - Meshes with vertices, normals, UVs
  - Skeleton joints hierarchy
  - Skin (bone weights per vertex)
  - Animations (rotation + translation keyframes)

UE5 imports glTF natively.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pygltflib
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Accessor, BufferView, Buffer, Skin,
    Animation, AnimationChannel, AnimationChannelTarget, AnimationSampler,
)

from nwextractor.convert.cgf_parser import CgfFile, MeshData, Bone, Vec3
from nwextractor.convert.caf_parser import CafAnimation


def export_glb(cgf: CgfFile, out_path: Path) -> Path | None:
    """Export a CgfFile to a binary glTF (.glb) file."""
    if not cgf.meshes:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    gltf = GLTF2()
    gltf.scene = 0
    gltf.scenes = [Scene(nodes=[0])]

    # Accumulate all binary data
    bin_data = bytearray()

    mesh = cgf.meshes[0]  # Primary mesh
    has_skeleton = bool(cgf.bones) and bool(mesh.bone_weights)

    # ─── Build binary buffers ───

    # Positions
    pos_offset = len(bin_data)
    pos_min = [float("inf")] * 3
    pos_max = [float("-inf")] * 3
    for v in mesh.vertices:
        bin_data += struct.pack("<fff", v.x, v.y, v.z)
        pos_min[0] = min(pos_min[0], v.x)
        pos_min[1] = min(pos_min[1], v.y)
        pos_min[2] = min(pos_min[2], v.z)
        pos_max[0] = max(pos_max[0], v.x)
        pos_max[1] = max(pos_max[1], v.y)
        pos_max[2] = max(pos_max[2], v.z)
    pos_size = len(bin_data) - pos_offset

    # Normals (if available)
    norm_offset = len(bin_data)
    has_normals = len(mesh.normals) == len(mesh.vertices)
    if has_normals:
        for n in mesh.normals:
            bin_data += struct.pack("<fff", n.x, n.y, n.z)
    norm_size = len(bin_data) - norm_offset

    # UVs (flip V for glTF: glTF uses top-left origin, CryEngine uses bottom-left)
    uv_offset = len(bin_data)
    has_uvs = len(mesh.uvs) == len(mesh.vertices)
    if has_uvs:
        for uv in mesh.uvs:
            bin_data += struct.pack("<ff", uv.u, 1.0 - uv.v)
    uv_size = len(bin_data) - uv_offset

    # Indices
    idx_offset = len(bin_data)
    use_u32 = max(mesh.indices, default=0) > 65535
    for idx in mesh.indices:
        if use_u32:
            bin_data += struct.pack("<I", idx)
        else:
            bin_data += struct.pack("<H", idx)
    idx_size = len(bin_data) - idx_offset

    # Joints + Weights (for skinned meshes)
    joints_offset = len(bin_data)
    weights_offset = 0
    if has_skeleton and mesh.bone_weights:
        for bw in mesh.bone_weights:
            # JOINTS_0: 4 × uint16
            bin_data += struct.pack("<HHHH", *[min(b, 65535) for b in bw.bone_ids])
        joints_size = len(bin_data) - joints_offset

        weights_offset = len(bin_data)
        for bw in mesh.bone_weights:
            # WEIGHTS_0: 4 × float, normalized
            w = list(bw.weights)
            total = sum(w)
            if total > 0:
                w = [x / total for x in w]
            else:
                w = [1.0, 0.0, 0.0, 0.0]
            bin_data += struct.pack("<ffff", *w)
        weights_size = len(bin_data) - weights_offset
    else:
        joints_size = 0
        weights_size = 0

    # Inverse bind matrices (identity for now — proper transforms need more format RE)
    ibm_offset = len(bin_data)
    if has_skeleton:
        identity = [
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1,
        ]
        for _ in cgf.bones:
            bin_data += struct.pack("<16f", *identity)
    ibm_size = len(bin_data) - ibm_offset

    # ─── Build glTF structure ───

    # Buffer
    gltf.buffers = [Buffer(byteLength=len(bin_data))]

    # BufferViews
    bv_idx = 0

    # BV 0: positions
    gltf.bufferViews = [BufferView(buffer=0, byteOffset=pos_offset, byteLength=pos_size, target=34962)]
    pos_bv = bv_idx; bv_idx += 1

    # BV 1: normals
    if has_normals:
        gltf.bufferViews.append(BufferView(buffer=0, byteOffset=norm_offset, byteLength=norm_size, target=34962))
        norm_bv = bv_idx; bv_idx += 1

    # BV 2: UVs
    if has_uvs:
        gltf.bufferViews.append(BufferView(buffer=0, byteOffset=uv_offset, byteLength=uv_size, target=34962))
        uv_bv = bv_idx; bv_idx += 1

    # BV 3: indices
    gltf.bufferViews.append(BufferView(buffer=0, byteOffset=idx_offset, byteLength=idx_size, target=34963))
    idx_bv = bv_idx; bv_idx += 1

    # BV 4-5: joints + weights
    if has_skeleton and joints_size > 0:
        gltf.bufferViews.append(BufferView(buffer=0, byteOffset=joints_offset, byteLength=joints_size, target=34962))
        joints_bv = bv_idx; bv_idx += 1
        gltf.bufferViews.append(BufferView(buffer=0, byteOffset=weights_offset, byteLength=weights_size, target=34962))
        weights_bv = bv_idx; bv_idx += 1

    # BV 6: inverse bind matrices
    if has_skeleton and ibm_size > 0:
        gltf.bufferViews.append(BufferView(buffer=0, byteOffset=ibm_offset, byteLength=ibm_size))
        ibm_bv = bv_idx; bv_idx += 1

    # Accessors
    acc_idx = 0
    gltf.accessors = []

    # Acc 0: positions
    gltf.accessors.append(Accessor(
        bufferView=pos_bv, componentType=5126, count=len(mesh.vertices),
        type="VEC3", max=pos_max, min=pos_min,
    ))
    pos_acc = acc_idx; acc_idx += 1

    # Acc 1: normals
    if has_normals:
        gltf.accessors.append(Accessor(
            bufferView=norm_bv, componentType=5126, count=len(mesh.normals), type="VEC3",
        ))
        norm_acc = acc_idx; acc_idx += 1

    # Acc 2: UVs
    if has_uvs:
        gltf.accessors.append(Accessor(
            bufferView=uv_bv, componentType=5126, count=len(mesh.uvs), type="VEC2",
        ))
        uv_acc = acc_idx; acc_idx += 1

    # Acc 3: indices
    gltf.accessors.append(Accessor(
        bufferView=idx_bv,
        componentType=5125 if use_u32 else 5123,
        count=len(mesh.indices), type="SCALAR",
    ))
    idx_acc = acc_idx; acc_idx += 1

    # Acc 4-5: joints + weights
    if has_skeleton and joints_size > 0:
        gltf.accessors.append(Accessor(
            bufferView=joints_bv, componentType=5123, count=len(mesh.bone_weights), type="VEC4",
        ))
        joints_acc = acc_idx; acc_idx += 1

        gltf.accessors.append(Accessor(
            bufferView=weights_bv, componentType=5126, count=len(mesh.bone_weights), type="VEC4",
        ))
        weights_acc = acc_idx; acc_idx += 1

    # Acc 6: inverse bind matrices
    if has_skeleton and ibm_size > 0:
        gltf.accessors.append(Accessor(
            bufferView=ibm_bv, componentType=5126, count=len(cgf.bones), type="MAT4",
        ))
        ibm_acc = acc_idx; acc_idx += 1

    # Primitive attributes
    attributes = pygltflib.Attributes(POSITION=pos_acc)
    if has_normals:
        attributes.NORMAL = norm_acc
    if has_uvs:
        attributes.TEXCOORD_0 = uv_acc
    if has_skeleton and joints_size > 0:
        attributes.JOINTS_0 = joints_acc
        attributes.WEIGHTS_0 = weights_acc

    primitive = Primitive(attributes=attributes, indices=idx_acc)

    # Mesh
    gltf.meshes = [Mesh(primitives=[primitive])]

    # Nodes
    if has_skeleton:
        # Node 0: root scene node with mesh + skin
        # Nodes 1..N: skeleton joints
        mesh_node = Node(mesh=0, skin=0)
        gltf.nodes = [mesh_node]

        joint_node_indices = []
        for i, bone in enumerate(cgf.bones):
            node_idx = len(gltf.nodes)
            joint_node_indices.append(node_idx)
            joint_node = Node(name=bone.name)
            gltf.nodes.append(joint_node)

        # Set up parent-child relationships for skeleton
        root_joints = []
        for i, bone in enumerate(cgf.bones):
            if bone.parent_index < 0 or bone.parent_index >= len(cgf.bones):
                root_joints.append(joint_node_indices[i])
            else:
                parent_node_idx = joint_node_indices[bone.parent_index]
                if gltf.nodes[parent_node_idx].children is None:
                    gltf.nodes[parent_node_idx].children = []
                gltf.nodes[parent_node_idx].children.append(joint_node_indices[i])

        # Add root joints as children of scene
        gltf.nodes[0].children = root_joints

        # Skin
        gltf.skins = [Skin(
            joints=joint_node_indices,
            inverseBindMatrices=ibm_acc,
            skeleton=root_joints[0] if root_joints else None,
        )]
    else:
        gltf.nodes = [Node(mesh=0)]

    # Scene
    gltf.scenes = [Scene(nodes=[0])]

    # Set binary blob
    gltf.set_binary_blob(bytes(bin_data))

    # Save as .glb
    gltf.save(str(out_path))
    return out_path


def export_animation_glb(anim: CafAnimation, out_path: Path,
                         bone_name_map: dict[int, str] | None = None,
                         bones: list | None = None) -> Path | None:
    """Export a CAF animation to GLB with proper bone names.

    Args:
        anim: Parsed animation data.
        out_path: Output .glb file path.
        bone_name_map: Optional dict mapping controller_id → bone_name.
                       Built from the skeleton's CompiledBones chunk.
        bones: Optional list of Bone objects from the skeleton for hierarchy.

    If bone_name_map is provided, animation tracks use real bone names
    that match the skeletal mesh GLB, allowing UE5 to link them.
    """
    if not anim.tracks:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    gltf = GLTF2()
    gltf.scene = 0
    bin_data = bytearray()

    # Build bone nodes — use real names from skeleton if available
    if bones and bone_name_map:
        # Build full skeleton hierarchy with correct names
        gltf.nodes = [Node(name="Armature")]
        track_node_map: dict[int, int] = {}

        for bone in bones:
            node_idx = len(gltf.nodes)
            track_node_map[bone.controller_id] = node_idx
            gltf.nodes.append(Node(name=bone.name))

        # Set up parent-child from skeleton hierarchy
        root_joints = []
        for i, bone in enumerate(bones):
            node_idx = track_node_map[bone.controller_id]
            if bone.parent_index < 0 or bone.parent_index >= len(bones):
                root_joints.append(node_idx)
            else:
                parent_bone = bones[bone.parent_index]
                parent_node_idx = track_node_map.get(parent_bone.controller_id)
                if parent_node_idx is not None:
                    if gltf.nodes[parent_node_idx].children is None:
                        gltf.nodes[parent_node_idx].children = []
                    gltf.nodes[parent_node_idx].children.append(node_idx)
                else:
                    root_joints.append(node_idx)

        gltf.nodes[0].children = root_joints
    else:
        # Fallback: use controller IDs as names
        gltf.nodes = [Node(name="Armature")]
        track_node_map = {}
        for track in anim.tracks:
            node_idx = len(gltf.nodes)
            track_node_map[track.controller_id] = node_idx
            name = bone_name_map.get(track.controller_id, f"bone_{track.controller_id:08x}") if bone_name_map else f"bone_{track.controller_id:08x}"
            gltf.nodes.append(Node(name=name))

    # Make all bone nodes children of root
    gltf.nodes[0].children = list(range(1, len(gltf.nodes)))
    gltf.scenes = [Scene(nodes=[0])]

    # Build animation
    gltf.bufferViews = []
    gltf.accessors = []
    samplers = []
    channels = []

    for track in anim.tracks:
        node_idx = track_node_map[track.controller_id]

        # Rotation track
        if track.rotation_keys:
            # Time buffer
            time_offset = len(bin_data)
            t_min = float("inf")
            t_max = float("-inf")
            for key in track.rotation_keys:
                bin_data += struct.pack("<f", key.time)
                t_min = min(t_min, key.time)
                t_max = max(t_max, key.time)
            time_size = len(bin_data) - time_offset

            # Rotation buffer (quaternion: x, y, z, w)
            rot_offset = len(bin_data)
            for key in track.rotation_keys:
                r = key.rotation
                bin_data += struct.pack("<ffff", r.x, r.y, r.z, r.w)
            rot_size = len(bin_data) - rot_offset

            # BufferViews
            time_bv = len(gltf.bufferViews)
            gltf.bufferViews.append(BufferView(buffer=0, byteOffset=time_offset, byteLength=time_size))
            rot_bv = len(gltf.bufferViews)
            gltf.bufferViews.append(BufferView(buffer=0, byteOffset=rot_offset, byteLength=rot_size))

            # Accessors
            time_acc = len(gltf.accessors)
            gltf.accessors.append(Accessor(
                bufferView=time_bv, componentType=5126,
                count=len(track.rotation_keys), type="SCALAR",
                min=[t_min], max=[t_max],
            ))
            rot_acc = len(gltf.accessors)
            gltf.accessors.append(Accessor(
                bufferView=rot_bv, componentType=5126,
                count=len(track.rotation_keys), type="VEC4",
            ))

            # Sampler + Channel
            sampler_idx = len(samplers)
            samplers.append(AnimationSampler(input=time_acc, output=rot_acc, interpolation="LINEAR"))
            channels.append(AnimationChannel(
                sampler=sampler_idx,
                target=AnimationChannelTarget(node=node_idx, path="rotation"),
            ))

        # Position track
        if track.position_keys:
            time_offset = len(bin_data)
            t_min = float("inf")
            t_max = float("-inf")
            for key in track.position_keys:
                bin_data += struct.pack("<f", key.time)
                t_min = min(t_min, key.time)
                t_max = max(t_max, key.time)
            time_size = len(bin_data) - time_offset

            pos_offset = len(bin_data)
            for key in track.position_keys:
                p = key.position
                bin_data += struct.pack("<fff", p.x, p.y, p.z)
            pos_size = len(bin_data) - pos_offset

            time_bv = len(gltf.bufferViews)
            gltf.bufferViews.append(BufferView(buffer=0, byteOffset=time_offset, byteLength=time_size))
            pos_bv = len(gltf.bufferViews)
            gltf.bufferViews.append(BufferView(buffer=0, byteOffset=pos_offset, byteLength=pos_size))

            time_acc = len(gltf.accessors)
            gltf.accessors.append(Accessor(
                bufferView=time_bv, componentType=5126,
                count=len(track.position_keys), type="SCALAR",
                min=[t_min], max=[t_max],
            ))
            pos_acc = len(gltf.accessors)
            gltf.accessors.append(Accessor(
                bufferView=pos_bv, componentType=5126,
                count=len(track.position_keys), type="VEC3",
            ))

            sampler_idx = len(samplers)
            samplers.append(AnimationSampler(input=time_acc, output=pos_acc, interpolation="LINEAR"))
            channels.append(AnimationChannel(
                sampler=sampler_idx,
                target=AnimationChannelTarget(node=node_idx, path="translation"),
            ))

    if channels:
        anim_name = Path(anim.file_path).stem if anim.file_path else "animation"
        gltf.animations = [Animation(name=anim_name, samplers=samplers, channels=channels)]

    gltf.buffers = [Buffer(byteLength=len(bin_data))]
    gltf.set_binary_blob(bytes(bin_data))
    gltf.save(str(out_path))
    return out_path
