"""Run with Blender: blender --background --factory-startup --python this_file.py

Uses a real ZBrush GoZ file: a PolySphere whose 6 polygroup borders were
creased (Crease PG), giving 48 creased edges.
"""

import os
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_multires_import import (  # noqa: E402  (also enables the add-on)
    FakeOperator,
    MultiresImportTests,
    bpy,
    gob,
    unittest,
)

creases = gob.creases
SAMPLE = Path(__file__).resolve().parent / "data" / "PolySphere_creased.GoZ"


def goz_blocks(path):
    """Return {tag: payload} for the blocks of a .GoZ file."""
    data = Path(path).read_bytes()
    blocks, i = {}, 32
    while i + 8 <= len(data):
        tag, length = struct.unpack_from("<II", data, i)
        if tag == 0 or length < 8:
            break
        blocks[tag] = data[i + 16 : i + length]
        i += length
    return blocks


def creased_edges(blocks):
    """Creased edges (as vertex pairs) described by a GoZ file's blocks."""
    faces = blocks[0x4E21]
    codes = blocks[0x9C42]
    edges = set()
    for face in range(len(codes)):
        verts = struct.unpack_from("<4I", faces, face * 16)
        count = 3 if verts[3] == 0xFFFFFFFF else 4
        for corner in range(count):
            if (codes[face] >> (2 * corner)) & 0b11:
                pair = (verts[corner], verts[(corner + 1) % count])
                edges.add(tuple(sorted(pair)))
    return edges


class CreaseTests(MultiresImportTests):
    """Reuses the temporary GoZ folder set-up from the Multires tests."""

    def setUp(self):
        super().setUp()
        self.prefs.import_multires = False
        self.prefs.import_creases = True
        self.prefs.export_creases = True
        self.sphere_path = str(self.project / "PolySphere.GoZ")
        shutil.copy(SAMPLE, self.sphere_path)

    def crease_values(self, obj):
        attribute = obj.data.attributes.get(creases.CREASE_ATTRIBUTE)
        if attribute is None:
            return []
        return [d.value for d in attribute.data]

    def import_sphere(self):
        FakeOperator().GoZit(self.sphere_path)
        return bpy.data.objects["PolySphere"]

    def polygroup_border_edges(self, obj):
        face_sets = obj.data.attributes[".sculpt_face_set"].data
        edge_faces = {}
        for poly in obj.data.polygons:
            for key in poly.edge_keys:
                edge_faces.setdefault(key, []).append(face_sets[poly.index].value)
        return {k for k, groups in edge_faces.items() if len(set(groups)) > 1}

    def test_import_creases_polygroup_borders(self):
        obj = self.import_sphere()
        values = self.crease_values(obj)
        creased = {e.key for e, v in zip(obj.data.edges, values) if v > 0}
        self.assertEqual(len(creased), 48)
        self.assertEqual(creased, self.polygroup_border_edges(obj))

    def test_import_off(self):
        self.prefs.import_creases = False
        obj = self.import_sphere()
        self.assertEqual(self.crease_values(obj), [])

    def test_export_matches_zbrush_creases(self):
        obj = self.import_sphere()
        out_dir = self.project / "out"
        out_dir.mkdir()
        FakeOperator().exportGoZ(bpy.context.scene, obj, str(out_dir))
        exported = goz_blocks(out_dir / "PolySphere.GoZ")
        self.assertIn(0x9C42, exported)
        # GoB may rotate face corners, so compare creased edges, not bytes.
        self.assertEqual(
            creased_edges(exported), creased_edges(goz_blocks(SAMPLE))
        )
        self.assertEqual(len(creased_edges(exported)), 48)

    def test_export_without_creases_writes_no_block(self):
        self.prefs.import_creases = False
        obj = self.import_sphere()
        out_dir = self.project / "out"
        out_dir.mkdir()
        FakeOperator().exportGoZ(bpy.context.scene, obj, str(out_dir))
        self.assertNotIn(0x9C42, goz_blocks(out_dir / "PolySphere.GoZ"))

    # The inherited Multires tests already run in test_multires_import.py.
    for name in [n for n in dir(MultiresImportTests) if n.startswith("test_")]:
        locals()[name] = None
    del name


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CreaseTests)
    unittest.TextTestRunner(verbosity=2).run(suite)
