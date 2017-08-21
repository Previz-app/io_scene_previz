import os
import pathlib
import queue
import site
import sys
import tempfile
import time
import threading

# Dependencies path, depending if we are in an installed plugin
# or in development move within a virtual env
def sitedir():
    path = pathlib.Path(__file__).parent
    if 'VIRTUAL_ENV' in os.environ:
        env = pathlib.Path(os.environ['VIRTUAL_ENV'])
        v = sys.version_info
        path = env / 'lib/python{}.{}/site-packages'.format(v.major, v.minor)
    return str(path.resolve())
site.addsitedir(sitedir())

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, path_reference_mode

import previz
from . import tasks
from . import three_js_exporter


bl_info = {
    'name': "Previz integration",
    'author': "Previz (info@previz.co)",
    'version': (1, 0, 4),
    'blender': (2, 76, 0),
    'location': "File > Export",
    'description': "Upload scenes to Previz.",
    'category': 'Import-Export',
    'warning': 'This a WIP development version'
}

version_string = '.'.join([str(x) for x in bl_info['version']])

TEMPORARY_DIRECTORY_PREFIX = 'blender-{}-'.format(__name__)


def previz_preferences(context):
    prefs = context.user_preferences.addons[__name__].preferences
    return prefs.api_root, prefs.api_token


###################
# Debugging tools #
###################


def log_function_name(func):
    if bpy.app.debug:
        print('====', func.__qualname__)


def log_call(func):
    def wrapper(*args, **kwargs):
        log_function_name(func)
        return func(*args, **kwargs)

    return wrapper


def log_execute(func):
    def wrapper(self, context):
        log_function_name(func)
        return func(self, context)
    return wrapper


log_draw = log_execute


def log_invoke(func):
    def wrapper(self, context, event):
        log_function_name(func)
        return func(self, context, event)
    return wrapper



class ExportPreviz(bpy.types.Operator):
    bl_idname = 'export_scene.previz'
    bl_label = 'Export scene to Previz'

    api_root = StringProperty(
        name='API root'
    )

    api_token = StringProperty(
        name='API token'
    )

    project_id = StringProperty(
        name='Previz project ID'
    )

    scene_id = StringProperty(
        name='Previz scene ID',
    )

    debug_cleanup = BoolProperty(
        name='Cleanup temporary folder',
        default=True,
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return True # Context check in the future

    @log_execute
    def execute(self, context):
        team_uuid = active.team(context)['id']

        fileno, path = tempfile.mkstemp(
            suffix = '.json',
            prefix = self.__class__.__name__,
            dir = bpy.context.user_preferences.filepaths.temporary_directory)

        export_path = pathlib.Path(path)

        task = tasks.PublishSceneTask(
            api_root = self.api_root,
            api_token = self.api_token,
            project_id = self.project_id,
            scene_id = self.scene_id,
            export_path = export_path,
            debug_cleanup = False
        )
        tasks.tasks_runner.add_task(context, task)

        return {'FINISHED'}


# TODO Should be an invoke
class ExportPrevizFromUI(bpy.types.Operator):
    bl_idname = 'export_scene.previz_from_ui'
    bl_label = 'Export scene to Previz'

    @classmethod
    def poll(cls, context):
        api_root, api_token = previz_preferences(context)
        api_root_is_valid = len(api_root) > 0
        api_token_is_valid = len(api_token) > 0
        active_scene_is_valid = active.is_valid(context)
        operator_is_valid = ExportPreviz.poll(context)
        return api_root_is_valid \
               and api_token_is_valid \
               and active_scene_is_valid \
               and operator_is_valid

    @log_invoke
    def invoke(self, context, event):
        api_root, api_token = previz_preferences(context)
        project_id = active.project(context)['id']
        scene_id = active.scene(context)['id']

        return bpy.ops.export_scene.previz(
            api_root=api_root,
            api_token=api_token,
            project_id=project_id,
            scene_id=scene_id
        )


class ExportPrevizFile(bpy.types.Operator, ExportHelper):
    bl_idname = 'export_scene.previz_file'
    bl_label = 'Export scene to a Previz file'

    filename_ext = ".json"
    filter_glob = StringProperty(
        default="*.json;",
        options={'HIDDEN'},
    )

    path_mode = path_reference_mode

    check_extension = True

    @log_execute
    def execute(self, context):
        filepath = pathlib.Path(self.as_keywords()['filepath'])
        with filepath.open('w') as fp:
            previz.export(three_js_exporter.build_scene(context), fp)
        return {'FINISHED'}


class CreateProject(bpy.types.Operator):
    bl_idname = 'export_scene.previz_new_project'
    bl_label = 'New Previz project'
    
    api_root = StringProperty(
        name='API root',
        options={'HIDDEN'}
    )

    api_token = StringProperty(
        name='API token',
        options={'HIDDEN'}
    )

    project_name = StringProperty(
        name='Project name'
    )

    @classmethod
    def poll(cls, context):
        api_root, api_token = previz_preferences(context)
        return len(api_root) > 0 and len(api_token) > 0

    @log_execute
    def execute(self, context):
        def on_done(context, data, project):
            active.teams = extract_all(data)
            active.set_project(context, project)

        team_uuid = active.team(context)['id']

        task = tasks.CreateProjectTask(
            api_root = self.api_root,
            api_token = self.api_token,
            project_name = self.project_name,
            team_uuid = team_uuid,
            on_done = on_done
        )
        tasks.tasks_runner.add_task(context, task)

        return {'FINISHED'}

    @log_invoke
    def invoke(self, context, event):
        self.api_root, self.api_token = previz_preferences(context)
        return context.window_manager.invoke_props_dialog(self)


class CreateScene(bpy.types.Operator):
    bl_idname = 'export_scene.previz_new_scene'
    bl_label = 'New Previz scene'

    api_root = StringProperty(
        name='API root',
        options={'HIDDEN'}
    )

    api_token = StringProperty(
        name='API token',
        options={'HIDDEN'}
    )

    scene_name = StringProperty(
        name='Scene name'
    )

    # XXX check if a valid project is set
    @classmethod
    def poll(cls, context):
        api_root, api_token = previz_preferences(context)
        is_project_valid = active.project(context) is not None
        return len(api_root) > 0 and len(api_token) > 0 and is_project_valid

    @log_execute
    def execute(self, context):
        def on_done(context, data, scene):
            active.teams = extract_all(data)
            active.set_scene(context, scene)

        task = tasks.CreateSceneTask(
            api_root = self.api_root,
            api_token = self.api_token,
            scene_name = self.scene_name,
            project_id = active.project(context)['id'],
            on_done = on_done
        )
        tasks.tasks_runner.add_task(context, task)

        return {'FINISHED'}

    @log_invoke
    def invoke(self, context, event):
        self.api_root, self.api_token = previz_preferences(context)
        return context.window_manager.invoke_props_dialog(self)


class PrevizPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    api_root = StringProperty(
        name='API root',
        default='https://app.previz.co/api'
    )

    api_token = StringProperty(
        name='API token'
    )

    def draw(self, context):
        layout = self.layout

        layout.prop(self, 'api_root')
        
        row = layout.split(percentage=.9, align=False)
        row.prop(self, 'api_token')

        op = layout.operator('wm.url_open', text="Tokens", icon='URL')
        # Should be dynamic, depending on api_root
        op.url = 'https://app.previz.co/account/api'


#########
# Panel #
#########


class Active(object):
    default_team = '[Need to refresh]'
    default_name = 'Select'
    default_id = 'empty_id'

    def __init__(self):
        self.teams = [] # Structure teams.projects.scenes

    @property
    def is_refreshed(self):
        return len(self.teams) > 0

    def is_valid(self, context):
        return self.scene(context) is not None

    # Teams

    def team(self, context):
        return self.getitem(
            self.teams,
            context.scene.previz_active_team_id
        )

    def team_menu_items(self):
        def cb(other, context):
            return self.menu_items(self.teams, '[No team]')
        return cb

    def team_menu_update(self):
        def cb(other, context):
            projects = self.projects(context)
            project = projects[0] if len(projects) > 0 else None
            self.set_project(context, project)
            self.log(context)
        return cb

    # Projects

    def projects(self, context):
        team = self.team(context)
        if not team:
            return []
        return team.get('projects')

    def project(self, context):
        return self.getitem(
            self.projects(context),
            context.scene.previz_active_project_id
        )

    def set_project(self, context, project):
        project_id_str = str(project['id']) if project is not None else Active.default_id
        context.scene.previz_active_project_id = project_id_str

    def project_menu_items(self):
        def cb(other, context):
            return self.menu_items(self.projects(context), '[No project]')
        return cb

    def project_menu_update(self):
        def cb(other, context):
            scenes = self.scenes(context)
            scene = scenes[0] if len(scenes) > 0 else None
            self.set_scene(context, scene)
            self.log(context)
        return cb

    # Scenes

    def scenes(self, context):
        project = self.project(context)
        if not project:
            return []
        return project.get('scenes')

    def scene(self, context):
        return self.getitem(
            self.scenes(context),
            context.scene.previz_active_scene_id
        )

    def set_scene(self, context, scene):
        scene_id_str = str(scene['id']) if scene is not None else Active.default_id
        context.scene.previz_active_scene_id = scene_id_str

    def scene_menu_items(self):
        def cb(other, context):
            return self.menu_items(self.scenes(context), '[No scene]')
        return cb

    def scene_menu_update(self):
        def cb(other, context):
            self.log(context)
        return cb

    # utils

    def log(self, context):
        print('Active: team {}, project {}, scene {}'.format(
            self.as_string(self.team(context)),
            self.as_string(self.project(context)),
            self.as_string(self.scene(context))
            )
        )

    @staticmethod
    def getitem(items, id, default=None):
        for item in items:
            if item['id'] == id:
                return item
        return default

    @staticmethod
    def contains(items, id):
        for item in items:
            if item[id] == id:
                return True
        return False

    @staticmethod
    def menu_items(items, default_item_name):
        number = -1
        ret = []
        for item in items:
            name_key = Active.name_key(item)

            id   = item['id']
            name = item[name_key]
            number += 1
            ret.append((id, name, name, number))
        if len(ret) == 0:
            number += 1
            item = (Active.default_id, default_item_name, default_item_name, number)
            ret.append(item)
        return ret

    @staticmethod
    def as_string(item):
        if item is None:
            return str(None)
        name_key = Active.name_key(item)
        return '{}[id:{}]'.format(item[name_key], item['id'])

    @staticmethod
    def name_key(item):
        if 'title' in item:
            return 'title'
        return 'name'

    @staticmethod
    def as_id(prop):
        if prop == '':
            return -1
        return int(prop)


def extract(data, next_name = None):
    ret = {
        'id': data['id'],
        'title': data['title']
    }
    if next_name is None:
        return ret

    ret[next_name] = []
    return ret, ret[next_name]


def extract_all(teams_data):
    teams = []
    for t in teams_data:
        team, projects = extract(t, 'projects')
        teams.append(team)
        for p in t['projects']:
            project, scenes = extract(p, 'scenes')
            projects.append(project)
            for s in p['scenes']:
                scene = extract(s)
                scenes.append(scene)
    return teams


active = Active()
new_plugin_version = None


class RefreshProjects(bpy.types.Operator):
    bl_idname = 'export_scene.previz_refresh_projects'
    bl_label = 'Refresh Previz projects'

    @classmethod
    def poll(cls, context):
        api_root, api_token = previz_preferences(context)
        return len(api_root) > 0 and len(api_token) > 0

    @log_execute
    def execute(self, context):
        def on_get_all(context, data):
            active.teams = extract_all(data)

        def on_updated_plugins(context, data):
            global new_plugin_version
            new_plugin_version = data

        api_root, api_token = previz_preferences(context)
        task = tasks.RefreshAllTask(
            api_root,
            api_token,
            version_string,
            on_get_all,
            on_updated_plugins
        )
        tasks.tasks_runner.add_task(context, task)
        return {'FINISHED'}


class PrevizPanel(bpy.types.Panel):
    bl_label = "Previz"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    bpy.types.Scene.previz_active_team_id = EnumProperty(
        name='Team',
        items=active.team_menu_items(),
        update=active.team_menu_update()
    )

    bpy.types.Scene.previz_active_project_id = EnumProperty(
        name='Project',
        items=active.project_menu_items(),
        update=active.project_menu_update()
    )

    bpy.types.Scene.previz_active_scene_id = EnumProperty(
        name='Scene',
        items=active.scene_menu_items(),
        update=active.scene_menu_update()
    )

    @log_draw
    def draw(self, context):
        api_root, api_token = previz_preferences(context)

        if len(api_root) == 0 or len(api_token) == 0:
            self.layout.label('Set the API info in the User Preferences.')
            self.layout.label('Search Previz in the Add-ons tab.')
            self.layout.operator('screen.userpref_show')
            return

        if active.is_refreshed:
            row = self.layout.row()
            row.prop(context.scene, 'previz_active_team_id')

            row = self.layout.row()
            row.prop(context.scene, 'previz_active_project_id')
            row.operator('export_scene.previz_new_project', text='', icon='NEW')

            row = self.layout.row()
            row.prop(context.scene, 'previz_active_scene_id')
            row.operator('export_scene.previz_new_scene', text='', icon='NEW')

            self.layout.operator(
                'export_scene.previz_from_ui',
                text='Update Previz scene',
                icon='EXPORT'
            )

        self.layout.operator(
            'export_scene.previz_refresh_projects',
            text='Refresh',
            icon='FILE_REFRESH'
        )

        if new_plugin_version:
            text = 'New addon: v' + new_plugin_version['version']
            op = self.layout.operator('wm.url_open', text=text, icon='URL')
            op.url = new_plugin_version['downloadUrl']


################
# Registration #
################


def menu_export(self, context):
    self.layout.operator(ExportPrevizFile.bl_idname, text="Previz (three.js .json)")

# TODO To be activated when API endpoint back in API v2
#def menu_image_upload(self, context):
    #self.layout.operator(UploadImage.bl_idname, text="Upload image to Previz")

def register():
    bpy.utils.register_class(ExportPreviz)
    bpy.utils.register_class(ExportPrevizFromUI)
    bpy.utils.register_class(ExportPrevizFile)
    bpy.utils.register_class(RefreshProjects)
    bpy.utils.register_class(CreateProject)
    bpy.utils.register_class(CreateScene)

    bpy.utils.register_class(PrevizPreferences)

    bpy.utils.register_class(PrevizPanel)

    bpy.types.INFO_MT_file_export.append(menu_export)
    #bpy.types.IMAGE_MT_image.append(menu_image_upload)

    tasks.register()

def unregister():
    bpy.utils.unregister_class(ExportPreviz)
    bpy.utils.unregister_class(ExportPrevizFromUI)
    bpy.utils.unregister_class(ExportPrevizFile)
    bpy.utils.unregister_class(RefreshProjects)
    bpy.utils.unregister_class(CreateProject)
    bpy.utils.unregister_class(CreateScene)

    bpy.utils.unregister_class(PrevizPreferences)

    bpy.utils.unregister_class(PrevizPanel)

    bpy.types.INFO_MT_file_export.remove(menu_export)
    #bpy.types.IMAGE_MT_image.remove(menu_image_upload)

    tasks.unregister()
