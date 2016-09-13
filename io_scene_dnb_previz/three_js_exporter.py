import itertools
import json
import pathlib
import uuid

import bpy
import bpy_extras.io_utils
import mathutils

from . import __name__ as generator


AXIS_CONVERSION = bpy_extras.io_utils.axis_conversion(to_forward='Z', to_up='Y').to_4x4()


class UuidBuilder(object):
    def __init__(self, dns = 'previz.online'):
        self.namespace = uuid.uuid5(uuid.NAMESPACE_DNS, dns)

    def __call__(self, name = None):
        return str(self.uuid(name)).upper()

    def uuid(self, name):
        if name is None:
            return uuid.uuid4()
        return uuid.uuid5(self.namespace, name)


buildUuid = UuidBuilder()

def flat_list(iterable):
    def flatten(values):
        try:
            for value in values:
                for iterated in flatten(value):
                    yield iterated
        except TypeError:
            yield values

    return list(flatten(iterable))


def build_metadata(context):
    return {
        'version': 4.4,
        'type': 'Object',
        'generator': generator,
        'sourceFile': pathlib.Path(bpy.data.filepath).name
    }


def build_scene_root(context, children):
    return {
        'type': 'Scene',
        'matrix': flat_list(mathutils.Matrix()),
        'uuid': buildUuid(),
        'children': children,
        'background': color2threejs(context.scene.world.horizon_color)
    }


def exportable_objects(context):
    return (o for o in context.visible_objects if o.type == 'MESH')


def uvs_iterator(uvset):
    return (d.uv for d in uvset.data)


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


def parse_geometry(g):
    g.calc_tessface()

    vertices = (v.co for v in g.vertices)
    vertices_count = len(g.vertices)

    uvsets_count = len(g.tessface_uv_textures)
    uv_index = itertools.count()
    uvsets = (uvs_iterator(uvs) for uvs in g.tessface_uv_textures)

    three_js_face = ThreeJSFaceBuilder(uvsets_count)
    faces = (three_js_face(face) for face in g.tessfaces)
    faces_count = len(g.tessfaces)

    return faces, vertices,  uvsets, faces_count, vertices_count, uvsets_count


def build_geometry(blender_geometry):
    faces, vertices, uvsets, faces_count, vertices_count, uvsets_count = parse_geometry(blender_geometry)

    return {
        'data': {
            'metadata': {
                'version': 3,
                'generator': generator,
            },
            'name': blender_geometry.name,
            'faces': flat_list(faces),
            'uvs': [flat_list(uvset) for uvset in uvsets],
            'vertices': flat_list(vertices)
        },
        'uuid': buildUuid(),
        'type': 'Geometry'
    }


def build_object(blender_object, geometry_uuid):
    return {
        'name': blender_object.name,
        'uuid': buildUuid(),
        'matrix': flat_list((AXIS_CONVERSION * blender_object.matrix_world).transposed()),
        'visible': True,
        'type': 'Mesh',
        'geometry': geometry_uuid
    }


def build_three_object(blender_object):
    geometry = build_geometry(blender_object.data)
    object = build_object(blender_object, geometry['uuid'])
    return object, geometry


def build_objects(context):
    objects = []
    geometries = []

    for o in exportable_objects(context):
        object, geometry = build_three_object(o)
        objects.append(object)
        geometries.append(geometry)

    return build_scene_root(context, objects), geometries


def build_three_js_scene(context):
    ret = {}

    scene_root, geometries = build_objects(context)

    return {

        'animations': [],
        'geometries': geometries,
        'images': [],
        'materials': [],
        'metadata': build_metadata(context),
        'object': scene_root,
        'textures': []
    }


def color2threejs(color):
    def to_int(v):
        if v < 0.0:
            return 0
        if v > 1.0:
            return 255
        return round(v*255)

    return 256*256*to_int(color.r) + 256*to_int(color.g) + to_int(color.b)


def export(context, fp):
    scene = build_three_js_scene(context)
    json.dump(scene, fp, indent=1, sort_keys=True)
