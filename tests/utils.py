from contextlib import contextmanager
from functools import wraps
import json
import os
import pathlib
import random
import shutil
import string
import tempfile

import bpy

import io_scene_previz

BLENDS_DIR_NAME = 'blends'

PREVIZ_API_ROOT_ENVVAR = 'PREVIZ_API_ROOT'
PREVIZ_API_TOKEN_ENVVAR = 'PREVIZ_API_TOKEN'
PREVIZ_TEAM_UUID_ENVVAR= 'PREVIZ_TEAM_UUID'

from previz import PrevizProject



class ApiDecorators(object):
    def __init__(
        self,
        api_token,
        api_root,
        team_id,
        new_project_prefix = 'ut-',
        new_scene_prefix='ut-'):
        self.api_root = api_root
        self.api_token = api_token
        self.team_id = team_id
        self.new_project_prefix = new_project_prefix
        self.new_scene_prefix = new_scene_prefix

    @contextmanager
    def project_context(self, title):
        pp = PrevizProject(self.api_root, self.api_token)
        p = pp.new_project(self.new_project_prefix+title, self.team_id)
        try:
            yield p
        finally:
            pp.project_id = p['id']
            pp.delete_project()

    @contextmanager
    def scene_context(self, project_id, title):
        pp = PrevizProject(self.api_root, self.api_token, project_id)
        s = pp.new_scene(self.new_scene_prefix+title)
        try:
            yield s
        finally:
            pp.delete_scene(s['id'])

    def project(self, project_id):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                p = PrevizProject(self.api_root, self.api_token, project_id)
                project = p.project(include=['scenes'])
                func(project=project, *args, **kwargs)
            return wrapper
        return decorator

    def tempproject(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self.project_context(func.__qualname__) as project:
                func(project=project, *args, **kwargs)
        return wrapper

    def scene(self, scene_id):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                project_id = kwargs['project']['id']
                p = PrevizProject(self.api_root, self.api_token, project_id)
                scene = p.scene(scene_id, include=[])
                func(scene=scene, *args, **kwargs)
                #p = PrevizProject(self.api_root, self.api_token, project_id)
                #func(project=p.project(include=['scenes']), *args, **kwargs)
            return wrapper
        return decorator

    def tempscene(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            project_id = kwargs['project']['id']
            with self.scene_context(project_id, func.__qualname__) as scene:
                func(scene=scene, *args, **kwargs)
        return wrapper


class MakeTempDirectories(object):
    def __init__(self, prefix):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp(prefix=prefix + '-'))
        print('Made temporary directory {!r}'.format(str(self.tmpdir)))

    def __del__(self):
        if len(list(self.tmpdir.iterdir())) > 0:
            print('Temporary directory {!r} is not empty: not removing it.'.format(str(self.tmpdir)))
            return

        self.tmpdir.rmdir()
        print('Removed temporary directory {!r}'.format(str(self.tmpdir)))

    def __call__(self, func):
        tmpdir = self.tmpdir
        @wraps(func)
        def func_wrapper(*args, **kwargs):
            d = tmpdir / func.__qualname__
            d.mkdir()
            kwargs['tmpdir'] = pathlib.Path(d)
            func(*args, **kwargs)
            shutil.rmtree(str(d))
        return func_wrapper


def build_api_decorators():
    return ApiDecorators(os.environ[PREVIZ_API_TOKEN_ENVVAR],
                         os.environ[PREVIZ_API_ROOT_ENVVAR],
                         os.environ[PREVIZ_TEAM_UUID_ENVVAR])


def scene(name):
    """Decorator that loads a test .blend scene before a test"""
    def decorator(func):
        @wraps(func)
        def func_wrapper(*args, **kwargs):
            # Load .blend

            scenepath = pathlib.Path(__file__).with_name(BLENDS_DIR_NAME) / name
            bpy.ops.wm.open_mainfile(filepath=str(scenepath),
                                     load_ui=False)  # load_ui=True crashes blender in --background mode

            # Enable addons

            bpy.ops.wm.addon_enable(module=io_scene_previz.__name__)

            # Set API token
            prefs = bpy.context.user_preferences.addons[io_scene_previz.__name__].preferences
            prefs.api_root = os.environ[PREVIZ_API_ROOT_ENVVAR]
            prefs.api_token = os.environ[PREVIZ_API_TOKEN_ENVVAR]

            # Run test
            kwargs['scenepath'] = scenepath
            return func(*args, **kwargs)

        return func_wrapper
    return decorator


def object_names(objects = None):
    if objects is None:
        objects = bpy.data.objects
    return sorted([o.name for o in objects])


def load_three_js_json(path, strip_uuids=False):
    def strip(value):
        values = []

        if type(value) is dict:
            for key in ['geometry', 'uuid']:
                if key in value.keys():
                    del value[key]
            values = value.values()

        if type(value) is list:
            if len(value) > 0 and type(value[0]) is dict:
                child = value[0]

                if 'name' in child:
                    value.sort(key=lambda x: x['name'])

                if 'data' in child:
                    value.sort(key=lambda x: x['data']['name'])

            values = value

        for value in values:
            strip(value)

    with path.open() as fp:
        ret = json.load(fp)
        if strip_uuids:
            strip(ret)
        return ret


def run_previz_exporter(
        project_id=None,
        scene_id=None,
        debug_run_api_requests=True,
        debug_tmpdir=None,
        debug_cleanup=False,
        debug_run_modal=False):
    api_root, api_token = io_scene_previz.previz_preferences(bpy.context)
    kwargs = {
        'api_root': api_root,
        'api_token': api_token,
        'debug_run_api_requests': debug_run_api_requests,
        'debug_cleanup': debug_cleanup,
        'debug_run_modal': debug_run_modal,
        'project_id': project_id,
        'scene_id': scene_id
    }

    if debug_tmpdir is not None:
        kwargs['debug_tmpdir'] = str(debug_tmpdir)

    return bpy.ops.export_scene.previz(**kwargs)


def run_create_project(project_name):
    api_root, api_token = io_scene_previz.previz_preferences(bpy.context)
    bpy.ops.export_scene.previz_new_project(api_root=api_root, api_token=api_token, project_name=project_name)

    return max(PrevizProject(api_root, api_token).projects(), key=lambda p: p['id'])['id']


def delete_project(project_id):
    api_root, api_token = io_scene_previz.previz_preferences(bpy.context)
    PrevizProject(api_root, api_token, project_id).delete_project()


def set_project_state(project_id, state):
    api_root, api_token = io_scene_previz.previz_preferences(bpy.context)
    PrevizProject(api_root, api_token, project_id).set_state(state)


def random_project_name():
    token = ''.join(random.choice(string.ascii_lowercase) for i in range(10))
    return 'Test-Project-{}'.format(token)
