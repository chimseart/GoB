# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

"""Rebuild a Multires modifier on meshes sent from ZBrush at their highest level.

The ZBrush script "GoB_SendHighest" exports each subtool at its highest
subdivision level and writes a small sidecar file next to the .GoZ file
holding the number of subdivision levels the subtool has in ZBrush.
Only imports with a sidecar are rebuilt, so normal GoZ imports (which always
send the lowest level) are left untouched.
"""

import os

import bpy

SDIV_SUFFIX = ".GoB_SDiv.txt"
MODIFIER_NAME = "Multires"


def sidecar_path(goz_path):
    return os.path.splitext(goz_path)[0] + SDIV_SUFFIX


def consume_zbrush_levels(goz_path):
    """Return the ZBrush level count for this .GoZ file and delete the sidecar.

    Returns None when the file was not sent by GoB_SendHighest. The sidecar is
    removed after reading so a later normal GoZ export of the same subtool is
    not mistaken for a high-level export.
    """

    path = sidecar_path(goz_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rt", encoding="utf-8", errors="ignore") as f:
            text = f.read().strip().strip("\x00")
        levels = int(float(text))
    except (OSError, ValueError):
        levels = None
    try:
        os.remove(path)
    except OSError:
        pass
    if levels is None or levels < 1:
        return None
    return levels


def remove_multires(obj):
    """Remove Multires modifiers that would no longer fit the new topology."""

    for modifier in [m for m in obj.modifiers if m.type == "MULTIRES"]:
        obj.modifiers.remove(modifier)


def rebuild(obj, zbrush_levels, mode, report=None):
    """Add a Multires modifier and rebuild subdivision levels from the mesh.

    mode "ZBRUSH": rebuild the same number of levels the subtool has in
    ZBrush (zbrush_levels - 1 subdivisions above the base).
    mode "MAX": rebuild as many levels as Blender can find.

    Returns the number of levels rebuilt. Warnings go to `report(message)`.
    """

    if report is None:
        report = lambda message: print(f"GoB: {message}")  # noqa: E731

    if mode == "ZBRUSH" and zbrush_levels <= 1:
        return 0
    if not obj.data.polygons:
        return 0

    remove_multires(obj)
    modifier = obj.modifiers.new(MODIFIER_NAME, "MULTIRES")
    with bpy.context.temp_override(object=obj, active_object=obj):
        if len(obj.modifiers) > 1:
            bpy.ops.object.modifier_move_to_index(modifier=modifier.name, index=0)

        if mode == "MAX":
            try:
                bpy.ops.object.multires_rebuild_subdiv(modifier=modifier.name)
            except RuntimeError as error:
                report(f"could not rebuild subdivisions for {obj.name}: {error}")
        else:
            wanted = zbrush_levels - 1
            for _ in range(wanted):
                try:
                    bpy.ops.object.multires_unsubdivide(modifier=modifier.name)
                except RuntimeError:
                    break
            if modifier.total_levels < wanted:
                report(
                    f"{obj.name} has {zbrush_levels} levels in ZBrush, "
                    f"but Blender could only rebuild {modifier.total_levels + 1}."
                )

    if modifier.total_levels == 0:
        # Nothing to rebuild (e.g. triangles or non-grid topology).
        obj.modifiers.remove(modifier)
        return 0

    # Show the full detail, like the level that was active when sending.
    modifier.levels = modifier.total_levels
    modifier.sculpt_levels = modifier.total_levels
    modifier.render_levels = modifier.total_levels
    return modifier.total_levels
