"""Run with Blender: blender --background --factory-startup --python this_file.py

Exports a subdivided cube to .GoZ with GoB's own exporter (standing in for a
ZBrush highest-level export), then imports it and checks the Multires rebuild.
"""

import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path

import bpy  # noqa: I001 (bpy must load before addon_utils)
import addon_utils
import bmesh

ADDON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_ROOT.parent))

# GoB only knows Windows and macOS paths; pretend to be Windows on other systems.
if platform.system() not in {"Windows", "Darwin"}:
    os.environ.setdefault("PUBLIC", tempfile.mkdtemp())
    _real_system = platform.system
    platform.system = lambda: "Windows"
    addon_utils.enable(ADDON_ROOT.name, default_set=True)
    platform.system = _real_system
else:
    addon_utils.enable(ADDON_ROOT.name, default_set=True)

gob = sys.modules[ADDON_ROOT.name]
GoB_OT_import = gob.gob_import.GoB_OT_import
GoB_OT_export = gob.gob_export.GoB_OT_export
paths = gob.paths
utils = gob.utils
multires = gob.multires
# The add-on is loaded from sys.path, not an add-on folder, so the version
# lookup used when writing GoB_variables.zvr finds nothing.
utils.gob_version = lambda: str(gob.bl_info["version"])

# vertex counts of a cube after 0..3 Catmull-Clark subdivisions
CUBE_VERTS = [8, 26, 98, 386]


class FakeOperator:
    """Lets the import/export methods run without invoking the operators."""

    GoZit = GoB_OT_import.GoZit
    make_mesh = GoB_OT_import.make_mesh
    mesh_topology_matches = staticmethod(GoB_OT_import.mesh_topology_matches)
    _ensure_object_in_view_layer = staticmethod(
        GoB_OT_import._ensure_object_in_view_layer
    )
    exportGoZ = GoB_OT_export.exportGoZ

    def report(self, *args):
        pass


class MultiresImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.project = root / "GoZProjects" / "Default"
        self.project.mkdir(parents=True)
        (root / "GoZBrush").mkdir()
        paths.set_goz_path(str(root))
        self._orig_project_path = utils.get_project_path
        gob.gob_export.utils.get_project_path = lambda *a, **k: str(self.project) + os.sep

        self.prefs = utils.prefs()
        self.prefs.import_multires = True
        self.prefs.import_multires_levels = "ZBRUSH"
        self.goz_path = str(self.project / "Body.GoZ")
        self.write_high_goz(subdivisions=3)

    def tearDown(self):
        gob.gob_export.utils.get_project_path = self._orig_project_path
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        self.tmp.cleanup()

    def write_high_goz(self, subdivisions):
        """Write Body.GoZ as a cube subdivided `subdivisions` times."""
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        me = bpy.data.meshes.new("tmp")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2)
        bm.loops.layers.uv.new("UVMap")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new("Body", me)
        bpy.context.scene.collection.objects.link(obj)
        if subdivisions:
            sub = obj.modifiers.new("s", "SUBSURF")
            sub.levels = subdivisions
            depsgraph = bpy.context.evaluated_depsgraph_get()
            high = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
            obj.modifiers.clear()
            obj.data = high
        FakeOperator().exportGoZ(bpy.context.scene, obj, str(self.project))
        bpy.data.objects.remove(obj, do_unlink=True)

    def write_sidecar(self, levels):
        with open(multires.sidecar_path(self.goz_path), "wt") as f:
            f.write(str(levels))

    def import_body(self):
        FakeOperator().GoZit(self.goz_path)
        return bpy.data.objects["Body"]

    def multires_mod(self, obj):
        mods = [m for m in obj.modifiers if m.type == "MULTIRES"]
        self.assertLessEqual(len(mods), 1)
        return mods[0] if mods else None

    def test_match_zbrush_levels(self):
        self.write_sidecar(4)  # base + 3 subdivisions in ZBrush
        obj = self.import_body()
        mod = self.multires_mod(obj)
        self.assertIsNotNone(mod)
        self.assertEqual(mod.total_levels, 3)
        self.assertEqual(mod.levels, 3)
        self.assertEqual(mod.sculpt_levels, 3)
        self.assertEqual(len(obj.data.vertices), CUBE_VERTS[0])
        self.assertFalse(os.path.exists(multires.sidecar_path(self.goz_path)))

    def test_fewer_zbrush_levels_keeps_higher_base(self):
        self.write_sidecar(2)  # ZBrush base is already a subdivided mesh
        obj = self.import_body()
        mod = self.multires_mod(obj)
        self.assertEqual(mod.total_levels, 1)
        self.assertEqual(len(obj.data.vertices), CUBE_VERTS[2])

    def test_max_levels(self):
        self.prefs.import_multires_levels = "MAX"
        self.write_sidecar(2)
        obj = self.import_body()
        self.assertEqual(self.multires_mod(obj).total_levels, 3)
        self.assertEqual(len(obj.data.vertices), CUBE_VERTS[0])

    def test_single_level_has_no_multires(self):
        self.write_sidecar(1)
        obj = self.import_body()
        self.assertIsNone(self.multires_mod(obj))
        self.assertEqual(len(obj.data.vertices), CUBE_VERTS[3])

    def test_normal_goz_import_is_unchanged(self):
        obj = self.import_body()  # no sidecar
        self.assertIsNone(self.multires_mod(obj))
        self.assertEqual(len(obj.data.vertices), CUBE_VERTS[3])

    def test_option_off_ignores_and_clears_sidecar(self):
        self.prefs.import_multires = False
        self.write_sidecar(4)
        obj = self.import_body()
        self.assertIsNone(self.multires_mod(obj))
        self.assertFalse(os.path.exists(multires.sidecar_path(self.goz_path)))

    def test_reimport_replaces_existing_multires(self):
        self.write_sidecar(4)
        self.import_body()
        self.write_sidecar(4)
        obj = self.import_body()
        mod = self.multires_mod(obj)
        self.assertEqual(mod.total_levels, 3)
        self.assertEqual(len(obj.data.vertices), CUBE_VERTS[0])
        self.assertEqual(obj.modifiers[0], mod)

    def test_uvs_survive(self):
        self.write_sidecar(4)
        obj = self.import_body()
        self.assertGreater(len(obj.data.uv_layers), 0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], exit=False, verbosity=2)
