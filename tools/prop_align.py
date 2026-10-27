import math

import RLPy
from tools.animation import find_bone, skeleton_of
from tools.common import frame_time
from tools.ik import _add, _cross, _dot, _from_rl, _normalize, _q_between, _qinv, _qmul, _rotate, _scale, _sub
from tools.objects import find_by_name


def _world(node):
    transform = node.WorldTransform()
    position = transform.T()
    return [position.x, position.y, position.z], _from_rl(transform.R())


def _point(value):
    return [float(value[axis]) for axis in "xyz"] if isinstance(value, dict) else [float(v) for v in value]


def _to_rl_quat(q):
    return RLPy.RQuaternion(RLPy.RVector4(q[0], q[1], q[2], q[3]))


def _perpendicular(v, axis):
    return _normalize(_sub(v, _scale(axis, _dot(v, axis))))


def align_prop_to_hands(args):
    """Key a hand-linked prop's local transform so its grip point sits in the grip palm, its support point lies
    toward the support palm and its top faces `up` (default world +Z). Points are world positions on the prop
    at `frame` (e.g. from get_object_bounds of its parts); the prop must already be linked to grip_bone."""
    prop = find_by_name(args["name"])
    avatar, skeleton = skeleton_of(args["avatar_name"])
    # WorldTransform() only follows SetTime/SetValue after an explicit Update() inside one call; without it the
    # key_frame bone read below returned the pose at `frame` and the relink baked a wrong offset.
    RLPy.RGlobal.SetTime(frame_time(args["frame"]))
    avatar.Update()
    prop.Update()
    grip_bone = find_bone(skeleton, args.get("grip_bone", "CC_Base_R_Hand"))
    support_bone = find_bone(skeleton, args.get("support_bone", "CC_Base_L_Hand"))
    grip_pos, grip_rot = _world(grip_bone)
    support_pos, support_rot = _world(support_bone)
    palm_grip = _add(grip_pos, _rotate(grip_rot, _point(args.get("grip_palm_offset", [0, 8, 0]))))
    palm_support = _add(support_pos, _rotate(support_rot, _point(args.get("support_palm_offset", [0, 8, 0]))))

    prop_pos, prop_rot = _world(prop)
    grip = _point(args["grip_point"])
    support = _point(args["support_point"])
    top = _point(args["top_point"])

    src_axis = _normalize(_sub(support, grip))
    dst_axis = _normalize(_sub(palm_support, palm_grip))
    swing = _q_between(src_axis, dst_axis)
    up_now = _rotate(swing, _perpendicular(_sub(top, grip), src_axis))
    up_goal = _perpendicular(_point(args.get("up", [0, 0, 1])), dst_axis)
    angle = math.atan2(_dot(_cross(up_now, up_goal), dst_axis), _dot(up_now, up_goal))
    half = angle / 2.0
    roll = [dst_axis[0] * math.sin(half), dst_axis[1] * math.sin(half), dst_axis[2] * math.sin(half), math.cos(half)]
    delta = _qmul(roll, swing)

    new_rot = _qmul(delta, prop_rot)
    new_pos = _add(palm_grip, _rotate(delta, _sub(prop_pos, grip)))
    local_rot = _qmul(_qinv(grip_rot), new_rot)
    local_pos = _rotate(_qinv(grip_rot), _sub(new_pos, grip_pos))

    # A linked prop ignores its Transform position/rotation (only scale applies), so place it unlinked in world
    # space at key_frame and link it again with no alignment, which keeps that offset to the bone.
    control = prop.GetControl("Transform")
    local = prop.LocalTransform()  # keep alive: S() of a temporary returns garbage (SWIG)
    s = local.S()
    scale = RLPy.RVector3(s.x, s.y, s.z)
    key_time = frame_time(args.get("key_frame", 0))
    RLPy.RGlobal.SetTime(key_time)
    avatar.Update()
    prop.UnLink(key_time)
    bone_pos, bone_rot = _world(grip_bone)
    world_rot = _qmul(bone_rot, local_rot)
    world_pos = _add(bone_pos, _rotate(bone_rot, local_pos))
    control.SetValue(key_time, RLPy.RTransform(scale, _to_rl_quat(world_rot), RLPy.RVector3(*world_pos)))
    prop.Update()
    if prop.LinkTo(grip_bone, RLPy.ELinkObjectAlignType__None, key_time) != RLPy.RStatus.Success:
        raise RuntimeError("iClone could not link the prop back to %s" % grip_bone.GetName())
    RLPy.RGlobal.SetTime(frame_time(args["frame"]))
    avatar.Update()
    prop.Update()
    placed_pos, placed_rot = _world(prop)
    return {
        "status": "ok",
        "name": prop.GetName(),
        "key_frame": args.get("key_frame", 0),
        "transform_keys": control.GetKeyCount(),
        "hand_span_cm": math.sqrt(_dot(_sub(palm_support, palm_grip), _sub(palm_support, palm_grip))),
        "prop_span_cm": math.sqrt(_dot(_sub(support, grip), _sub(support, grip))),
        "expected_world_position": new_pos,
        "placed_world_position": placed_pos,
        "expected_world_rotation": new_rot,
        "placed_world_rotation": placed_rot,
        "rotation_error": 1.0 - abs(_dot4(new_rot, placed_rot)),
    }


def _bone_local(prop, bone):
    bone_pos, bone_rot = _world(bone)
    prop_pos, prop_rot = _world(prop)
    return _rotate(_qinv(bone_rot), _sub(prop_pos, bone_pos)), _qmul(_qinv(bone_rot), prop_rot)


def set_prop_bone_offset(args):
    """Relink a prop to a bone with an exact local offset (position cm + rotation quaternion in the bone frame)."""
    prop = find_by_name(args["name"])
    avatar, skeleton = skeleton_of(args["avatar_name"])
    bone = find_bone(skeleton, args.get("bone", "CC_Base_R_Hand"))
    local_pos = _point(args["local_position"])
    q = args["local_rotation"]
    local_rot = _normalize4([float(q["x"]), float(q["y"]), float(q["z"]), float(q["w"])])
    control = prop.GetControl("Transform")
    local = prop.LocalTransform()  # keep alive: S() of a temporary returns garbage (SWIG)
    s = local.S()
    scale = RLPy.RVector3(s.x, s.y, s.z)
    key_time = frame_time(args.get("key_frame", 0))
    RLPy.RGlobal.SetTime(key_time)
    avatar.Update()
    prop.UnLink(key_time)
    bone_pos, bone_rot = _world(bone)
    world_rot = _qmul(bone_rot, local_rot)
    world_pos = _add(bone_pos, _rotate(bone_rot, local_pos))
    control.SetValue(key_time, RLPy.RTransform(scale, _to_rl_quat(world_rot), RLPy.RVector3(*world_pos)))
    prop.Update()
    if prop.LinkTo(bone, RLPy.ELinkObjectAlignType__None, key_time) != RLPy.RStatus.Success:
        raise RuntimeError("iClone could not link the prop back to %s" % bone.GetName())
    check_frame = args.get("check_frame", args.get("key_frame", 0))
    RLPy.RGlobal.SetTime(frame_time(check_frame))
    avatar.Update()
    prop.Update()
    placed_pos, placed_rot = _bone_local(prop, bone)
    return {
        "status": "ok",
        "name": prop.GetName(),
        "check_frame": check_frame,
        "placed_local_position": placed_pos,
        "placed_local_rotation": placed_rot,
        "position_error_cm": math.sqrt(_dot(_sub(placed_pos, local_pos), _sub(placed_pos, local_pos))),
        "rotation_error": 1.0 - abs(_dot4(placed_rot, local_rot)),
    }


def _dot4(a, b):
    return sum(x * y for x, y in zip(a, b))  # ik._dot is 3D and would ignore w


def _normalize4(q):
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q]


def register(registry):
    point = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}}
    quat = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}, "w": {"type": "number"}}}
    registry["set_prop_bone_offset"] = {
        "handler": set_prop_bone_offset,
        "main_thread": True,
        "description": "Relinks a prop to an avatar bone (default CC_Base_R_Hand) with an exact local offset: local_position (cm) and local_rotation (quaternion x,y,z,w) in the bone frame, keyed at key_frame (default 0). Returns the offset measured back at check_frame.",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"}, "avatar_name": {"type": "string"}, "bone": {"type": "string"},
            "local_position": point, "local_rotation": quat, "key_frame": {"type": "integer"}, "check_frame": {"type": "integer"},
        }, "required": ["name", "avatar_name", "local_position", "local_rotation"]},
    }
    registry["align_prop_to_hands"] = {
        "handler": align_prop_to_hands,
        "main_thread": True,
        "description": "Keys a hand-linked prop (e.g. a shotgun linked to CC_Base_R_Hand) so grip_point sits in the grip palm, support_point points at the support palm and top_point faces up. Points are world positions on the prop at frame.",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"}, "avatar_name": {"type": "string"}, "frame": {"type": "integer"},
            "grip_point": point, "support_point": point, "top_point": point, "up": point,
            "grip_bone": {"type": "string"}, "support_bone": {"type": "string"},
            "grip_palm_offset": point, "support_palm_offset": point, "key_frame": {"type": "integer"},
        }, "required": ["name", "avatar_name", "frame", "grip_point", "support_point", "top_point"]},
    }
