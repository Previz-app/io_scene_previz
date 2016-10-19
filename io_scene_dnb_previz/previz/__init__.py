import collections
import json
import requests
import uuid


class PrevizProject(object):
    endpoints_masks = {
        'projects': '{root}/projects',
        'project':  '{root}/projects/{project_id:d}',
        'scene':    '{root}/projects/{project_id:d}/scene',
        'assets':   '{root}/projects/{project_id:d}/assets',
        'asset':    '{root}/projects/{project_id:d}/assets/{asset_id:d}',
        'state':    '{root}/projects/{project_id:d}/state',
    }

    def __init__(self, root, token, project_id = None):
        self.root = root
        self.token = token
        self.project_id = project_id

    def request(self, *args, **kwargs):
        return requests.request(*args,
                                headers=self.headers,
                                verify=False, # TODO: how to make it work on Mac / Windows ?
                                **kwargs)

    def update_scene(self, fp):
        r = self.request('POST',
                         self.url('scene'),
                         files={'file': fp})
        return r.json()

    def projects(self):
        r = self.request('GET',
                         self.url('projects'))
        return r.json()

    def new_project(self, project_name):
        data = {'title': project_name}
        return self.request('POST',
                            self.url('projects'),
                            data=data).json()

    def delete_project(self):
        self.request('DELETE',
                     self.url('project'))

    def assets(self):
        return self.request('GET',
                            self.url('assets')).json()

    def delete_asset(self, asset_id):
        self.request('DELETE',
                     self.url('asset', asset_id=asset_id))

    def upload_asset(self, fp):
        return self.request('POST',
                            self.url('assets'),
                            files={'file': fp}).json()

    def set_state(self, state):
        data = {'state': state}
        self.request('PUT',
                     self.url('state'),
                     data=data)

    def url(self, mask_name, **url_elems_override):
        url_elems = self.url_elems.copy()
        url_elems.update(url_elems_override)
        return self.endpoints_masks[mask_name].format(**url_elems)

    @property
    def url_elems(self):
        return {
            'root': self.root,
            'project_id': self.project_id,
        }

    @property
    def headers(self):
        return {'Authorization': 'Bearer {0}'.format(self.token)}


class UuidBuilder(object):
    def __init__(self, dns = 'app.previz.co'):
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


#############################################################################

UVSet = collections.namedtuple('UVSet',
                               ['name',
                                'coordinates'])

Mesh = collections.namedtuple('Mesh',
                             ['name',
                              'geometry_name',
                              'world_matrix',
                              'faces',
                              'vertices',
                              'uvsets'])


Scene = collections.namedtuple('Scene',
                               ['generator',
                                'source_file',
                                'background_color',
                                'objects'])


def build_metadata(scene):
    return {
        'version': 4.4,
        'type': 'Object',
        'generator': scene.generator,
        'sourceFile': scene.source_file
    }


def build_scene_root(scene, children):
    ret = {
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
        'children': children
    }

    if scene.background_color is not None:
        ret['background'] = scene.background_color

    return ret


def build_geometry(scene, mesh):
    return {
        'data': {
            'metadata': {
                'version': 3,
                'generator': scene.generator,
            },
            'name': mesh.geometry_name,
            'faces': flat_list(mesh.faces),
            'uvs': [flat_list(uvset.coordinates) for uvset in mesh.uvsets],
            'vertices': flat_list(mesh.vertices)
        },
        'uuid': buildUuid(),
        'type': 'Geometry'
    }


def build_user_data(mesh):
    return {'previz': {
            'uvsetNames': [uvset.name for uvset in mesh.uvsets]
        }
    }


def build_object(mesh, geometry_uuid):
    return {
        'name': mesh.name,
        'uuid': buildUuid(),
        'matrix': flat_list(mesh.world_matrix),
        'visible': True,
        'type': 'Mesh',
        'geometry': geometry_uuid,
        'userData': build_user_data(mesh)
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
