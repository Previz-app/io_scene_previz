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
        yield face

        uv_indices = [next(self.uv_indices) for i in range(len(face))]
        for i in range(self.uvsets_count):
            yield uv_indices


    def type(self, face):
        """
        See https://github.com/mrdoob/three.js/wiki/JSON-Model-format-3
        """
        has_uvsets = self.uvsets_count > 0
        is_quad = len(face) == 4
        return (int(is_quad) << 0) + (int(has_uvsets) << 3 )


def build_uvset(uvset):
    return previz.UVSet(uvset.name, (d.uv for d in uvset.data))


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
    world_matrix = (AXIS_CONVERSION @ blender_object.matrix_world).transposed()
    
    geometry_name, faces, vertices, uvsets = parse_geometry(blender_object.data)
    
    return previz.Mesh(name,
                       geometry_name,
                       world_matrix,
                       faces,
                       vertices,
                       uvsets)

def parse_geometry(blender_geometry):
    g = blender_geometry
    # All face geometry in 2.8 is defined as loop triangles
    g.calc_loop_triangles()

    # Count the vertices in our geom, and figure out how many uv sets we need to keep three happy
    vertices = (v.co for v in g.vertices)
    vertices_count = len(g.vertices)
    uvsets_count = len(g.uv_layers)
    uvsets = list(build_uvset(uvset) for uvset in g.uv_layers)

    # Set our base builder with the uv sets to build
    three_js_face = ThreeJSFaceBuilder(uvsets_count)

    # This gets dark
    # We need to loop over the triangles of the faces,
    # BUT the way we handle uv mapping internally in the dag relies on 
    # all the faces being defined as quads 
    # So we'll first want to convert these triangles into Quads 
    # Consequtive triangles in the set are paired, and can be merged into a single quad
    # We loop through the triangles in sets of 2, then get the unqiue vertex points from the 
    # 6 points (a[0], a[1], a[2] + b[0], b[1], b[2]) to turn into q[0],q[1],q[2],q[3]
    # Then pass that quad over to the three_js_face logic to turn it into the format threejs wants
    faces = []
    iterable = iter(g.loop_triangles)
    for item in iterable:
        # Get the triangles 2 at a time 
        first =  list(item.vertices)
        second = list(next(iterable).vertices)

        # Take all the vertexes in the first, then only the unique point from the second
        quadface = first + [vertex for vertex in second if vertex not in first]

        # Convert this quad for the threejs format, and append to our faces array
        faces.extend(three_js_face(quadface))

    return g.name, faces, vertices, uvsets


def world_color(context):
    if context.scene.world == None:
        return None
    return color2threejs(context.scene.world.color)


def exportable_objects(context):
    return (o for o in context.visible_objects if o.type == 'MESH')


def build_objects(context):
    for o in exportable_objects(context):
        yield parse_mesh(o)


def build_scene(context):
    return previz.Scene(generator,
                        pathlib.Path(bpy.data.filepath).name,
                        world_color(context),
                        build_objects(context))
