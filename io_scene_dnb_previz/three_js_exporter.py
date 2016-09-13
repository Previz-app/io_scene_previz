import itertools
import pathlib

import bpy
import bpy_extras.io_utils
import mathutils

import previz

from . import __name__ as generator


AXIS_CONVERSION = bpy_extras.io_utils.axis_conversion(to_forward='Z', to_up='Y').to_4x4()


class ThreeJSFaceBuilder(object):
    def __init__(self, uvsets_count):
        self.uvsets_count = uvsets_count
        self.uv_indices = itertools.count()

    def __call__(self, face):
        yield self.type(face)
        yield face.vertices

        uv_indices = [next(self.uv_indices) for i in range(len(face.vertices))]
        for i in range(self.uvsets_count):
            yield uv_indices


    def type(self, face):
        """
        See https://github.com/mrdoob/three.js/wiki/JSON-Model-format-3
        """
        has_uvsets = self.uvsets_count > 0
        is_quad = len(face.vertices) == 4
        return (int(is_quad) << 0) + (int(has_uvsets) << 3 )


def uvs_iterator(uvset):
    return (d.uv for d in uvset.data)


def color2threejs(color):
    def to_int(v):
        if v < 0.0:
            return 0
        if v > 1.0:
            return 255
        return round(v*255)

    return 256*256*to_int(color.r) + 256*to_int(color.g) + to_int(color.b)


def parse_mesh(blender_object):
    name = blender_object.name
    world_matrix = (AXIS_CONVERSION * blender_object.matrix_world).transposed()
    
    geometry_name, faces, vertices, uvsets = parse_geometry(blender_object.data)
    
    return previz.Mesh(name,
                       geometry_name,
                       world_matrix,
                       faces,
                       vertices,
                       uvsets)


def parse_geometry(blender_geometry):
    g = blender_geometry
    
    g.calc_tessface()

    vertices = (v.co for v in g.vertices)
    vertices_count = len(g.vertices)

    uvsets_count = len(g.tessface_uv_textures)
    uvsets = (uvs_iterator(uvs) for uvs in g.tessface_uv_textures)

    three_js_face = ThreeJSFaceBuilder(uvsets_count)
    faces = (three_js_face(face) for face in g.tessfaces)
    faces_count = len(g.tessfaces)

    return g.name, faces, vertices, uvsets


def exportable_objects(context):
    return (o for o in context.visible_objects if o.type == 'MESH')


def build_objects(context):
    for o in exportable_objects(context):
        yield parse_mesh(o)


def build_scene(context):
    return previz.Scene(generator,
                        pathlib.Path(bpy.data.filepath).name,
                        color2threejs(context.scene.world.horizon_color),
                        build_objects(context))
