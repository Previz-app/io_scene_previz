import pathlib
import queue
import shutil
import sys
import tempfile

import addon_utils
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, path_reference_mode


sys.path.append(str(pathlib.Path(__file__).parent))
import previz

from . import utils
from . import three_js_exporter


bl_info = {
    'name': "dandelion + burdock's Previz integration",
    'author': "Charles Flèche (charles.fleche@free.fr)",
    'version': (0, 0, 7),
    'blender': (2, 76, 0),
    'location': "File > Export",
    'description': "Upload scenes to Previz.",
    'category': 'Import-Export'
}


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


####################
# Export to Previz #
####################


class ExportPreviz(utils.BackgroundTasksOperator):
    bl_idname = 'export_scene.previz'
    bl_label = 'Export scene to Previz'

    debug_run_modal = utils.BackgroundTasksOperator.debug_run_modal

    api_root = StringProperty(
        name='API root'
    )

    api_token = StringProperty(
        name='API token'
    )

    project_id = IntProperty(
        name='Previz project ID',
        default=-1
    )

    debug_cleanup = BoolProperty(
        name='Cleanup temporary folder',
        default=True,
        options={'HIDDEN'}
    )

    debug_tmpdir = StringProperty(
        name="Temporary directory absolute path",
        description="Absolute path to temporarily store assets. If empty, a path will be generated automatically.",
        options={'HIDDEN'}
    )

    debug_run_api_requests = BoolProperty(
        name="Run API requests",
        description="Run the requets againsts the Previz API.",
        default=True,
        options={'HIDDEN'}
    )

    def __init__(self):
        utils.BackgroundTasksOperator.__init__(self)

        self.g = {}

    @classmethod
    def poll(cls, context):
        api_root, api_token = previz_preferences(context)
        api_root_is_valid = len(api_root) > 0
        api_token_is_valid = len(api_token) > 0
        previz_project_is_valid = context.scene.previz_project_id >=0

        return api_root_is_valid and api_token_is_valid and previz_project_is_valid

    def build_tasks(self, context):
        tasks = [
            {'func': ExportPreviz.task_make_tmpdir},
            {'func': self.build_task_report('Made temporary directory {tmpdir}')},
            {'func': self.build_task_report('exporting three.js JSON')},
            {'func': ExportPreviz.task_export_three_js}
        ]

        if self.debug_run_api_requests:
            tasks.extend([
                {'func': self.build_task_report('starting API calls')},
                {'func': self.build_task_report('uploading scene')},
                {'func': ExportPreviz.task_update_previz_scene,
                 'run_in_subprocess': True},
                {'func': self.build_task_report('uploading assets')},
                {'func': ExportPreviz.task_update_previz_assets,
                 'run_in_subprocess': True},
                {'func': self.build_task_report('updating state')},
                {'func': ExportPreviz.task_set_previz_state,
                 'run_in_subprocess': True},
                {'func': self.build_task_report('done all API calls')}
            ])

        if self.debug_cleanup:
            tasks.extend([
                {'func': ExportPreviz.task_cleanup_tmpdir},
                {'func': self.build_task_report('removed temporary directory {tmpdir}')}
            ])

        tasks.append({'func': self.build_task_report('done')})

        self.g['context'] = context # This is probably not the safest, but only a main process task uses it

        return tasks

    def build_task_report(self, msg):
        def task(g):
            self.report({'INFO'}, 'Previz: ' + msg.format(**g))
            return g
        return task

    @staticmethod
    def task_make_tmpdir(g):
        tmpdir = pathlib.Path(g['property_tmpdir'])

        make_tmp = True
        if tmpdir.absolute() and not tmpdir.exists():
            try:
                tmpdir.mkdir(parents=True)
                make_tmp = False
            except:
                pass

        if make_tmp:
            tmpdir = pathlib.Path(tempfile.mkdtemp(prefix=TEMPORARY_DIRECTORY_PREFIX,
                                                   dir=bpy.context.user_preferences.filepaths.temporary_directory))

        g['tmpdir'] = tmpdir
        return g

    @staticmethod
    def task_export_three_js(g):
        with utils.ThreeJSExportPaths(g['tmpdir']).scene.open('w') as fp:
            previz.export(three_js_exporter.build_scene(g['context']), fp)
        return g

    @staticmethod
    def task_cleanup_tmpdir(g):
        shutil.rmtree(str(g['tmpdir']))
        return g

    @staticmethod
    def task_update_previz_scene(g):
        p = utils.ThreeJSExportPaths(g['tmpdir'])
        g['project'].update_scene(p.scene.open('rb'))
        return g

    @staticmethod
    def task_update_previz_assets(g):
        p = utils.ThreeJSExportPaths(g['tmpdir'])
        local_assets_names = [x.name for x in p.assets]

        for online_asset in g['project'].assets():
            if online_asset['name'] in local_assets_names:
                g['project'].delete_asset(online_asset['id'])

        for local_asset in p.assets:
            g['project'].upload_asset(local_asset.open('rb'))

        return g

    @staticmethod
    def task_set_previz_state(g):
        g['project'].set_state('viewer')
        return g

    def task_done(self, result):
        self.g.update(result)

    def task_args(self):
        args = (self.g,)
        kwargs = {}
        return args, kwargs

    def cancel(self, context):
        self.report({'INFO'}, 'Previz export cancelled')
        super(ExportPreviz, self).cancel(context)

    @log_execute
    def execute(self, context):
        if len(self.api_root) == 0 :
            self.report({'ERROR_INVALID_INPUT'}, 'No Previz API root specified')
            return {'CANCELLED'}
        
        if len(self.api_token) == 0 :
            self.report({'ERROR_INVALID_INPUT'}, 'No Previz API token specified')
            return {'CANCELLED'}

        if self.project_id < 0:
            self.report({'ERROR_INVALID_INPUT'}, 'No valid Previz project ID specified')
            return {'CANCELLED'}

        self.g['property_tmpdir'] = self.debug_tmpdir
        self.g['project'] = utils.PrevizProject(self.api_root,
                                                self.api_token,
                                                self.project_id)

        return super(ExportPreviz, self).execute(context)

    @log_invoke
    def invoke(self, context, event):
        self.api_root, self.api_token = previz_preferences(context)
        self.project_id = context.scene.previz_project_id

        return self.execute(context)


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
        project_data = utils.PrevizProject(self.api_root,
                                           self.api_token).new_project(self.project_name)
        context.scene.previz_project_name = project_data['title']
        context.scene.previz_project_id = project_data['id']
        return {'FINISHED'}

    @log_invoke
    def invoke(self, context, event):
        self.api_root, self.api_token = previz_preferences(context)
        return context.window_manager.invoke_props_dialog(self)


class UploadImage(utils.BackgroundTasksOperator):
    bl_idname = 'export_scene.previz_upload_image'
    bl_label = 'Export image to Previz'

    debug_run_modal = utils.BackgroundTasksOperator.debug_run_modal

    api_token = StringProperty(
        name='API token'
    )

    project_id = IntProperty(
        name='Previz project ID',
        default=-1
    )

    filepath = StringProperty(
        name='Image path',
        subtype='FILE_PATH',
    )

    @classmethod
    def poll(cls, context):
        is_valid_image = hasattr(context.space_data, 'image') and not context.space_data.image.packed_file
        
        api_root, api_token = previz_preferences(context)
        api_root_is_valid = len(api_root) > 0
        api_token_is_valid = len(api_token) > 0
        
        previz_project_is_valid = context.scene.previz_project_id >= 0
        
        return is_valid_image and api_root_is_valid and api_token_is_valid and previz_project_is_valid

    def build_tasks(self, context):
        filepath = pathlib.Path(self.filepath)
        tasks = [
            {'func': self.build_task_upload(self.api_root, self.api_token, self.project_id, filepath)},
            {'func': self.build_task_done_message(filepath)},
        ]
        return tasks

    def build_task_upload(self, api_root, api_token, project_id, filepath):
        def task():
            def progress_callback(encoder):
                print('Uploading {} {} / {}'.format(str(filepath), encoder.bytes_read, encoder.len))
            p = utils.PrevizProject(api_root, api_token, project_id)
            p.upload_asset(filepath.name, filepath.open('rb'), progress_callback)
        return task

    def build_task_done_message(self, filepath):
        def task():
            self.report({'INFO'}, 'Previz: uploaded asset {!s}'.format(filepath))
        return task

    def task_done(self, result):
        pass

    def task_args(self):
        return (), {}

    def cancel(self, context):
        self.report({'INFO'}, 'Previz asset {} export cancelled'.format(self.filepath))
        super(UploadImage, self).cancel(context)

    @log_execute
    def execute(self, context):
        if len(self.api_root) == 0 :
            self.report({'ERROR_INVALID_INPUT'}, 'No Previz API root specified')
            return {'CANCELLED'}
        
        if len(self.api_token) == 0 :
            self.report({'ERROR_INVALID_INPUT'}, 'No Previz API token specified')
            return {'CANCELLED'}

        if self.project_id < 0:
            self.report({'ERROR_INVALID_INPUT'}, 'No valid Previz project ID specified')
            return {'CANCELLED'}

        filepath = pathlib.Path(self.filepath)
        if not filepath.exists():
            self.report({'ERROR_INVALID_INPUT'}, '{!s} does not exist'.format(filepath))
            return {'CANCELLED'}

        return super(UploadImage, self).execute(context)

    @log_invoke
    def invoke(self, context, event):
        self.api_root, self.api_token = previz_preferences(context)
        self.project_id = context.scene.previz_project_id

        image = context.space_data.image
        filepath = bpy.path.abspath(image.filepath, library=image.library)
        self.filepath = str(pathlib.Path(filepath).resolve())

        return self.execute(context)


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
        op.url = 'https://app.previz.co/settings#/api'


#########
# Panel #
#########


class PrevizProjectsEnum(object):
    default_team = '[Need to refresh]'
    default_name = 'Select'
    default_id = -1

    def __init__(self):
        self.__projects_from_api = [] # id: name

    def menu_entries(self, current_project_id, current_project_name):
        projects = self.projects(current_project_id, current_project_name)
        projects.pop(self.default_id) # manually put it at the beginning of the entries

        projects_list = sorted(projects.items(),
                               key=lambda p: p[1], # project name
                               reverse=True)
        projects_list.append((self.default_id, self.default_name))

        return [self.menu_entry(id, name) for id, name in projects_list]

    def scene_menu_entries(self, current_project_id, current_scene_id, current_scene_name):
        scenes = self.scenes(current_project_id, current_scene_id, current_scene_name)
        scenes.pop(self.default_id) # manually put it at the beginning of the entries

        scenes_list = sorted(scenes.items(),
                             key=lambda p: p[1], # scene name
                             reverse=True)
        scenes_list.append((self.default_id, self.default_name))

        return [self.menu_entry(id, name) for id, name in scenes_list]

    def projects_for_menu_lookup(self, current_project_id, current_project_name):
        projects = self.projects(current_project_id, current_project_name)
        return dict((self.project_id_to_menu_id(id), (id, name)) for id, name in projects.items())

    def scenes_for_menu_lookup(self, current_project_id, current_scene_id, current_scene_name):
        scenes = self.scenes(current_project_id, current_scene_id, current_scene_name)
        return dict((self.project_id_to_menu_id(id), (id, name)) for id, name in scenes.items())

    @log_call
    def refresh(self, context):
        api_root, api_token = previz_preferences(context)
        api = utils.PrevizProject(api_root, api_token)
        all_data = api.get_all()

        team = all_data[0]
        context.scene.previz_team = team['name']

        self.__projects_from_api = all_data

    def projects(self, current_project_id, current_project_name):
        # Projects from API call cache

        ret = {}
        if len(self.__projects_from_api) > 0:
            team = self.__projects_from_api[0]
            ret.update(dict((p['id'], p['title']) for p in team['projects']))

        # Currently selected project

        ret[current_project_id] = current_project_name

        # default project

        ret[self.default_id] = self.default_name

        return ret

    def scenes(self, current_project_id, current_scene_id, current_scene_name):
        # Projects from API call cache

        ret = {}
        if len(self.__projects_from_api) > 0:
            team = self.__projects_from_api[0]
            scenes = self.scenes_for_project_id(current_project_id)
            ret.update(dict((s['id'], s['name']) for s in scenes))

        # Currently selected project

        ret[current_scene_id] = current_scene_name

        # default project

        ret[self.default_id] = self.default_name

        return ret

    def scenes_for_project_id(self, id):
        for team in self.__projects_from_api:
            for project in team['projects']:
                if project['id'] == id:
                    return project['scenes']
        return []

    @staticmethod
    def default_menu_id():
        return PrevizProjectsEnum.project_id_to_menu_id(PrevizProjectsEnum.default_id)

    @staticmethod
    def project_id_to_menu_id(id):
        return str(id)

    @staticmethod
    def menu_id_to_project_id(menu_id):
        return int(menu_id)

    @staticmethod
    def menu_entry(id, name):
        return PrevizProjectsEnum.project_id_to_menu_id(id), name, name


projects_enum = PrevizProjectsEnum()

def items_callback(self, context):
    current_project_id = context.scene.previz_project_id
    current_project_name = context.scene.previz_project_name
    return projects_enum.menu_entries(current_project_id, current_project_name)

def update_callback(self, context):
    current_project_id = context.scene.previz_project_id
    current_project_name = context.scene.previz_project_name
    menu_id = context.scene.previz_projects

    id, name = projects_enum.projects_for_menu_lookup(current_project_id, current_project_name)[menu_id]

    context.scene.previz_project_id = id
    context.scene.previz_project_name = name

    print('Set Previz project to "{}" (id: {})'.format(context.scene.previz_project_name,
                                                       context.scene.previz_project_id))

def scene_items_callback(self, context):
    current_project_id = context.scene.previz_project_id
    current_scene_id = context.scene.previz_scene_id
    current_scene_name = context.scene.previz_scene_name
    return projects_enum.scene_menu_entries(current_project_id, current_scene_id, current_scene_name)

def scene_update_callback(self, context):
    current_project_id = context.scene.previz_project_id
    current_scene_id = context.scene.previz_scene_id
    current_scene_name = context.scene.previz_scene_name
    menu_id = context.scene.previz_scenes

    id, name = projects_enum.scenes_for_menu_lookup(current_project_id, current_scene_id, current_scene_name)[menu_id]

    context.scene.previz_scene_id = id
    context.scene.previz_scene_name = name

    print('Set Previz scene to "{}" (id: {})'.format(context.scene.previz_scene_name,
                                                     context.scene.previz_scene_id))

class RefreshProjects(bpy.types.Operator):
    bl_idname = 'export_scene.previz_refresh_projects'
    bl_label = 'Refresh Previz projects'

    @classmethod
    def poll(cls, context):
        api_root, api_token = previz_preferences(context)
        return len(api_root) > 0 and len(api_token) > 0

    @log_execute
    def execute(self, context):
        previous_project = context.scene.previz_projects
        projects_enum.refresh(context)
        context.scene.previz_projects = previous_project
        return {'FINISHED'}


class PrevizPanel(bpy.types.Panel):
    bl_label = "Previz"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    bpy.types.Scene.previz_team = StringProperty(
        name="Team",
        default=PrevizProjectsEnum.default_team
    )

    bpy.types.Scene.previz_projects = EnumProperty(
        name='Project',
        items=items_callback,
        update=update_callback,
    )

    bpy.types.Scene.previz_scenes = EnumProperty(
        name='Scene',
        items=scene_items_callback,
        update=scene_update_callback,
    )

    bpy.types.Scene.previz_project_id = IntProperty(
        name = "Previz project ID",
        default=PrevizProjectsEnum.default_id
    )

    bpy.types.Scene.previz_project_name = StringProperty(
        name="Previz project name",
        default=PrevizProjectsEnum.default_name
    )

    bpy.types.Scene.previz_scene_id = IntProperty(
        name = "Previz scene ID",
        default=PrevizProjectsEnum.default_id
    )

    bpy.types.Scene.previz_scene_name = StringProperty(
        name="Previz scene name",
        default=PrevizProjectsEnum.default_name
    )

    @log_draw
    def draw(self, context):
        api_root, api_token = previz_preferences(context)

        if len(api_root) == 0 or len(api_token) == 0:
            self.layout.label('Set the API info in the User Preferences.')
            self.layout.label('Search Previz in the Add-ons tab.')
            self.layout.operator('screen.userpref_show')
            return

        self.layout.label('Team: {}'.format(context.scene.previz_team))
        self.layout.label('Go online to switch current project')

        row = self.layout.row()
        row.prop(context.scene, 'previz_projects')
        row.operator('export_scene.previz_refresh_projects', text='', icon='FILE_REFRESH')

        self.layout.prop(context.scene, 'previz_scenes')

        self.layout.operator('export_scene.previz_new_project', text='New project', icon='NEW')
        self.layout.operator('export_scene.previz',             text='Upload',      icon='EXPORT')


################
# Registration #
################


def menu_export(self, context):
    self.layout.operator(ExportPrevizFile.bl_idname, text="Previz (three.js .json)")

def menu_image_upload(self, context):
    self.layout.operator(UploadImage.bl_idname, text="Upload image to Previz")


@persistent
def set_project_selector_entry(dummy):
    project_id = bpy.context.scene.previz_project_id
    menu_id = PrevizProjectsEnum.project_id_to_menu_id(project_id)
    bpy.context.scene.previz_projects = menu_id


def register():
    bpy.utils.register_class(ExportPreviz)
    bpy.utils.register_class(ExportPrevizFile)
    bpy.utils.register_class(RefreshProjects)
    bpy.utils.register_class(CreateProject)
    bpy.utils.register_class(UploadImage)

    bpy.utils.register_class(PrevizPreferences)

    bpy.utils.register_class(PrevizPanel)

    bpy.types.INFO_MT_file_export.append(menu_export)
    bpy.types.IMAGE_MT_image.append(menu_image_upload)

    bpy.app.handlers.load_post.append(set_project_selector_entry)


def unregister():
    bpy.utils.unregister_class(ExportPreviz)
    bpy.utils.unregister_class(ExportPrevizFile)
    bpy.utils.unregister_class(RefreshProjects)
    bpy.utils.unregister_class(CreateProject)
    bpy.utils.unregister_class(UploadImage)

    bpy.utils.unregister_class(PrevizPreferences)

    bpy.utils.unregister_class(PrevizPanel)

    bpy.types.INFO_MT_file_export.remove(menu_export)
    bpy.types.IMAGE_MT_image.remove(menu_image_upload)
