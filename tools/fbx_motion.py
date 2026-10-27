import os

import RLPy

from tools.objects import find_by_name


_IMPORT_KINDS = {
    "standard_human": RLPy.EImportFbxOption_StandardHumanCharacter,
    "humanoid": RLPy.EImportFbxOption_Humanoid,
    "creature": RLPy.EImportFbxOption_Creature,
    "prop": RLPy.EImportFbxOption_Prop,
}


def _names(object_type):
    return {obj.GetID(): obj.GetName() for obj in RLPy.RScene.FindObjects(object_type)}


def import_fbx_character(args):
    path = args["path"]
    if not os.path.isfile(path):
        raise FileNotFoundError("FBX not found: %s" % path)
    kind = args.get("kind", "standard_human")
    if kind not in _IMPORT_KINDS:
        raise ValueError("Unsupported kind: %s" % kind)
    before = set(_names(RLPy.EObjectType_Avatar)) | set(_names(RLPy.EObjectType_Prop))
    result = RLPy.RFileIO.LoadFbxFile(path, _IMPORT_KINDS[kind])
    if result != RLPy.RStatus.Success:
        raise RuntimeError("iClone could not import the FBX as %s" % kind)
    added = [{"name": name, "type": "avatar"} for oid, name in _names(RLPy.EObjectType_Avatar).items() if oid not in before]
    added += [{"name": name, "type": "prop"} for oid, name in _names(RLPy.EObjectType_Prop).items() if oid not in before]
    if args.get("name") and len(added) == 1:
        find_by_name(added[0]["name"]).SetName(args["name"])
        added[0]["name"] = args["name"]
    return {"status": "ok", "kind": kind, "added": added}


def convert_fbx_to_motion(args):
    folder = args["save_folder"]
    if not os.path.isdir(folder):
        raise FileNotFoundError("Save folder not found: %s" % folder)
    results = []
    for path in args["paths"]:
        if not os.path.isfile(path):
            results.append({"path": path, "status": "missing"})
            continue
        before = set(os.listdir(folder))
        status = RLPy.RFileIO.ConvertFbxFileToRLMotion(path, folder)
        created = sorted(set(os.listdir(folder)) - before)
        results.append({"path": path, "status": "ok" if status == RLPy.RStatus.Success else "failed", "created": created})
    return {"results": results}


def apply_fbx_motion(args):
    path = args["path"]
    if not os.path.isfile(path):
        raise FileNotFoundError("FBX not found: %s" % path)
    obj = find_by_name(args["name"])
    time = RLPy.RGlobal.GetFps().IndexedFrameTime(args.get("start_frame", 0))
    result = RLPy.RFileIO.LoadFile(path, True, obj, time)
    if result != RLPy.RStatus.Success:
        raise RuntimeError("iClone could not apply the FBX motion to this object")
    return {"status": "ok", "name": obj.GetName(), "path": path, "start_frame": args.get("start_frame", 0)}


def export_fbx_motion(args):
    path = args["path"]
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise FileNotFoundError("Export folder not found: %s" % parent)
    obj = find_by_name(args["name"])
    fps = RLPy.RGlobal.GetFps()
    options = RLPy.EExportFbxOptions_AutoSkinRigidMesh | RLPy.EExportFbxOptions_RemoveHiddenMesh
    if args.get("motion_only", True):
        options |= RLPy.EExportFbxOptions_RemoveAllMesh
    if args.get("first_frame_tpose", False):
        options |= RLPy.EExportFbxOptions_TPoseOnMotionFirstFrame
    setting = RLPy.RExportFbxSetting()
    setting.SetOption(options)
    setting.SetOption2(RLPy.EExportFbxOptions2_UnityPreset | RLPy.EExportFbxOptions2_YUp | RLPy.EExportFbxOptions2_ResetBoneScale)
    setting.SetOption3(RLPy.EExportFbxOptions3__None)
    setting.EnableExportMotion(True)
    setting.SetExportMotionFps(fps)
    setting.SetExportMotionRange(RLPy.RRangePair(int(args["start_frame"]), int(args["end_frame"])))  # pair<int,int>, frames
    result = RLPy.RFileIO.ExportFbxFile(obj, path, setting)
    if result != RLPy.RStatus.Success:
        raise RuntimeError("iClone could not export FBX (the asset may require an export license)")
    return {"status": "ok", "name": obj.GetName(), "path": path, "start_frame": args["start_frame"], "end_frame": args["end_frame"]}


def register(registry):
    registry["import_fbx_character"] = {"handler": import_fbx_character, "main_thread": True, "description": "Imports an FBX as a character (kind: standard_human for CC exports, humanoid, creature) or prop, and returns the new objects.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "kind": {"type": "string", "enum": list(_IMPORT_KINDS)}, "name": {"type": "string"}}, "required": ["path"]}}
    registry["convert_fbx_to_motion"] = {"handler": convert_fbx_to_motion, "main_thread": True, "description": "Converts motion FBX files (e.g. Mixamo) into iClone .rlMotion files in save_folder; apply them with load_motion.", "inputSchema": {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}, "save_folder": {"type": "string"}}, "required": ["paths", "save_folder"]}}
    registry["apply_fbx_motion"] = {"handler": apply_fbx_motion, "main_thread": True, "description": "Applies a motion FBX (e.g. Mixamo) to an avatar at start_frame, like dropping the file onto it.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}, "start_frame": {"type": "integer", "minimum": 0}}, "required": ["name", "path"]}}
    registry["export_fbx_motion"] ={"handler": export_fbx_motion, "main_thread": True, "description": "Exports an avatar's animation between start_frame and end_frame as a Unity-preset FBX (motion_only drops the meshes, default true).", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}, "start_frame": {"type": "integer"}, "end_frame": {"type": "integer"}, "motion_only": {"type": "boolean"}, "first_frame_tpose": {"type": "boolean"}}, "required": ["name", "path", "start_frame", "end_frame"]}}
