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

"""ZBrush edge creases <-> Blender edge crease ("crease_edge" attribute).

ZBrush stores creases in the GoZ block tagged 0x9C42: one byte per face.
Bits (2k, 2k+1) of the byte belong to the face edge from corner k to
corner k+1, and ZBrush sets both bits (0b11) for a creased edge.
"""

import numpy as np

CREASE_TAG = b"\x42\x9c\x00\x00"
CREASE_ATTRIBUTE = "crease_edge"
_MAX_CORNERS = 4


def _edge_keys(v0, v1, vertex_count):
    low = np.minimum(v0, v1).astype(np.int64)
    high = np.maximum(v0, v1).astype(np.int64)
    return low * vertex_count + high


def apply_import(me, face_records, crease_bytes):
    """Set Blender edge creases from ZBrush per-face crease bytes.

    face_records are the raw GoZ face records (N x 4 vertex indices, the
    4th is 0xFFFFFFFF for triangles), in the corner order ZBrush wrote them.
    Edges are matched by their two vertices, so this works even though GoB
    may rotate or flip face corners when it builds the Blender mesh.
    Returns the number of creased edges.
    """

    records = np.asarray(face_records, dtype=np.uint32).reshape(-1, 4)
    face_count = min(len(records), len(crease_bytes))
    vertex_count = len(me.vertices)
    edge_count = len(me.edges)
    if not face_count or not edge_count:
        return 0

    records = records[:face_count].astype(np.int64)
    codes = np.frombuffer(crease_bytes, dtype=np.uint8, count=face_count)
    corner_count = np.where(records[:, 3] == 0xFFFFFFFF, 3, 4)

    starts, ends = [], []
    for corner in range(_MAX_CORNERS):
        has_corner = corner < corner_count
        creased = has_corner & (((codes >> (2 * corner)) & 0b11) != 0)
        rows = np.nonzero(creased)[0]
        next_corner = (corner + 1) % corner_count[rows]
        starts.append(records[rows, corner])
        ends.append(records[rows, next_corner])
    start_vertices = np.concatenate(starts)
    end_vertices = np.concatenate(ends)

    edge_vertices = np.empty(edge_count * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", edge_vertices)
    mesh_keys = _edge_keys(edge_vertices[0::2], edge_vertices[1::2], vertex_count)
    order = np.argsort(mesh_keys)
    sorted_keys = mesh_keys[order]

    crease_keys = _edge_keys(start_vertices, end_vertices, vertex_count)
    positions = np.searchsorted(sorted_keys, crease_keys)
    positions = np.clip(positions, 0, edge_count - 1)
    found = sorted_keys[positions] == crease_keys

    values = np.zeros(edge_count, dtype=np.float32)
    values[order[positions[found]]] = 1.0

    attribute = me.attributes.get(CREASE_ATTRIBUTE)
    if attribute is None or attribute.domain != "EDGE" or attribute.data_type != "FLOAT":
        if attribute is not None:
            me.attributes.remove(attribute)
        attribute = me.attributes.new(CREASE_ATTRIBUTE, "FLOAT", "EDGE")
    attribute.data.foreach_set("value", values)
    return int(np.count_nonzero(values))


def export_bytes(mesh):
    """Return ZBrush crease bytes (one per face) or None if nothing is creased."""

    attribute = mesh.attributes.get(CREASE_ATTRIBUTE)
    if attribute is None or attribute.domain != "EDGE" or not len(mesh.polygons):
        return None

    edge_crease = np.empty(len(mesh.edges), dtype=np.float32)
    attribute.data.foreach_get("value", edge_crease)
    if not np.any(edge_crease > 0.0):
        return None

    face_count = len(mesh.polygons)
    loop_starts = np.empty(face_count, dtype=np.int64)
    loop_totals = np.empty(face_count, dtype=np.int64)
    loop_edges = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)
    mesh.loops.foreach_get("edge_index", loop_edges)

    # A Blender loop's edge runs from its vertex to the next loop's vertex,
    # which is exactly ZBrush's "corner k to corner k+1" edge.
    loop_face = np.repeat(np.arange(face_count), loop_totals)
    corner = np.arange(len(loop_edges)) - np.repeat(loop_starts, loop_totals)
    creased = (edge_crease[loop_edges] > 0.0) & (corner < _MAX_CORNERS)

    codes = np.zeros(face_count, dtype=np.uint8)
    np.bitwise_or.at(
        codes,
        loop_face[creased],
        (0b11 << (2 * corner[creased])).astype(np.uint8),
    )
    return codes.tobytes()
