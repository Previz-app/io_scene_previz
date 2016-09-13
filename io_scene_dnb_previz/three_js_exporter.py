import collections
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


def build_metadata(scene):
    return {
        'version': 4.4,
        'type': 'Object',
        'generator': scene.generator,
        'sourceFile': scene.source_file
    }


def build_scene_root(scene, children):
    return {
        'type': 'Scene',
        'matrix': [
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0
        ],
        'uuid': buildUuid(),
        'children': children,
        'background': scene.background_color
    }


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


def build_geometry(scene, mesh):
    return {
        'data': {
            'metadata': {
                'version': 3,
                'generator': scene.generator,
            },
            'name': mesh.geometry_name,
            'faces': flat_list(mesh.faces),
            'uvs': [flat_list(uvset) for uvset in mesh.uvsets],
            'vertices': flat_list(mesh.vertices)
        },
        'uuid': buildUuid(),
        'type': 'Geometry'
    }


def build_object(mesh, geometry_uuid):
    return {
        'name': mesh.name,
        'uuid': buildUuid(),
        'matrix': flat_list(mesh.world_matrix),
        'visible': True,
        'type': 'Mesh',
        'geometry': geometry_uuid
    }


def build_objects(scene):
    objects = []
    geometries = []
    
    for mesh in scene.objects:
        geometry = build_geometry(scene, mesh)
        object = build_object(mesh, geometry['uuid'])
        
        objects.append(object)
        geometries.append(geometry)

    return build_scene_root(scene, objects), geometries


def build_three_js_scene(scene):
    ret = {}

    scene_root, geometries = build_objects(scene)

    return {

        'animations': [],
        'geometries': geometries,
        'images': [],
        'materials': [],
        'metadata': build_metadata(scene),
        'object': scene_root,
        'textures': []
    }


def export(scene, fp):
    scene = build_three_js_scene(scene)
    json.dump(scene, fp, indent=1, sort_keys=True)




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
    
    return Mesh(name,
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
    uv_index = itertools.count()
    uvsets = (uvs_iterator(uvs) for uvs in g.tessface_uv_textures)

    three_js_face = ThreeJSFaceBuilder(uvsets_count)
    faces = (three_js_face(face) for face in g.tessfaces)
    faces_count = len(g.tessfaces)

    return g.name, faces, vertices, uvsets


def exportable_objects(context):
    return (o for o in context.visible_objects if o.type == 'MESH')



class Scene(object):
    def __init__(self, context):
        self.context = context
    
    @property
    def generator(self):
        return generator
    
    @property
    def source_file(self):
        return pathlib.Path(bpy.data.filepath).name

    @property
    def background_color(self):
        return color2threejs(self.context.scene.world.horizon_color)
    
    @property
    def objects(self):
        for o in exportable_objects(self.context):
            yield parse_mesh(o)


Mesh = collections.namedtuple('Mesh',
                             ['name',
                              'geometry_name',
                              'world_matrix',
                              'faces',
                              'vertices',
                              'uvsets'])
