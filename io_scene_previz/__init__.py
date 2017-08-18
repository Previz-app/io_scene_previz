import os
import pathlib
import queue
import site
import shutil
import sys
import tempfile
import time
import threading

import addon_utils
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, path_reference_mode

from . import utils
site.addsitedir(utils.sitedir())

import previz
from . import progress
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

    debug_tmpdir = StringProperty(
        name="Temporary directory absolute path",
        description="Absolute path to temporarily store assets",
        options={'HIDDEN'}
    )

    debug_run_api_requests = BoolProperty(
        name="Run API requests",
        description="Run the requets againsts the Previz API",
        default=True,
        options={'HIDDEN'}
    )

    def __init__(self):
        utils.BackgroundTasksOperator.__init__(self)

        self.g = {}

    @classmethod
    def poll(cls, context):
        return True # Context check in the future

    def build_tasks(self, context):
        tasks = [
            {'func': ExportPreviz.task_make_tmpdir},
            {'func': self.build_task_report('Made temporary directory {tmpdir}')},
            {'func': self.build_task_report('Exporting three.js JSON')},
            {'func': ExportPreviz.task_export_three_js}
        ]

        if self.debug_run_api_requests:
            tasks.extend([
                {'func': self.build_task_report('Starting API calls')},
                {'func': self.build_task_report('Getting scene JSON url')},
                {'func': ExportPreviz.task_get_scene_json_url,
                 'run_in_subprocess': True},
                {'func': self.build_task_report('Uploading scene')},
                {'func': ExportPreviz.task_update_previz_scene,
                 'run_in_subprocess': True},
                #{'func': self.build_task_report('uploading assets')},
                #{'func': ExportPreviz.task_update_previz_assets,
                 #'run_in_subprocess': True},
                {'func': self.build_task_report('Updating state')},
                {'func': self.build_task_report('Done all API calls')}
            ])

        if self.debug_cleanup:
            tasks.extend([
                {'func': ExportPreviz.task_cleanup_tmpdir},
                {'func': self.build_task_report('Removed temporary directory {tmpdir}')}
            ])

        tasks.append({'func': self.build_task_report('Done')})

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
    def task_get_scene_json_url(g):
        scene = g['project'].scene(g['scene_id'], include=[])
        g['scene_json'] = scene['jsonUrl']
        return g

    @staticmethod
    def task_update_previz_scene(g):
        p = utils.ThreeJSExportPaths(g['tmpdir'])
        with p.scene.open('rb') as fd:
            g['project'].update_scene(g['scene_json'], fd)
        return g

    @staticmethod
    def task_update_previz_assets(g):
        p = utils.ThreeJSExportPaths(g['tmpdir'])
        local_assets_names = [x.name for x in p.assets]

        for online_asset in g['project'].assets():
            if online_asset['name'] in local_assets_names:
                g['project'].delete_asset(online_asset['id'])

        for local_asset in p.assets:
            with local_asset.open('rb') as fd:
                g['project'].upload_asset()

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

        if len(self.project_id) == 0:
            self.report({'ERROR_INVALID_INPUT'}, 'No valid Previz project ID specified')
            return {'CANCELLED'}

        if len(self.scene_id) == 0:
            self.report({'ERROR_INVALID_INPUT'}, 'No valid Previz scene ID specified')
            return {'CANCELLED'}

        self.g['property_tmpdir'] = self.debug_tmpdir
        self.g['project'] = previz.PrevizProject(self.api_root,
                                                 self.api_token,
                                                 self.project_id)
        self.g['scene_id'] = self.scene_id

        return super(ExportPreviz, self).execute(context)


class PrevizCancelUploadException(Exception):
    pass


class PublishSceneTask(progress.Task):
    def __init__(self, debug_cleanup = True, **kwargs):
        progress.Task.__init__(self)

        self.label = 'Publish scene'

        self.export_path = kwargs['export_path']
        self.debug_cleanup = debug_cleanup

        self.last_progress_notify_date = None

        self.queue_to_worker = queue.Queue()
        self.queue_to_main = queue.Queue()

        self.thread = threading.Thread(target=PublishSceneTask.thread_run,
                                       args=(self.queue_to_worker,
                                             self.queue_to_main),
                                       kwargs=kwargs)

    def run(self, context):
        super().run(context)

        self.progress = 0
        self.label = 'Exporting scene'
        self.notify()

        with self.export_path.open('w') as fp:
            previz.export(three_js_exporter.build_scene(context), fp)

        self.label = 'Publishing scene'
        self.notify()

        self.thread.start()

    def cleanup(self, context):
        if self.debug_cleanup and self.export_path.exists():
            self.export_path.unlink()

    def cancel(self):
        self.canceling()
        self.queue_to_worker.put((progress.REQUEST_CANCEL, None))

    @staticmethod
    def thread_run(queue_to_worker, queue_to_main, api_root, api_token, project_id, scene_id, export_path):
        def on_progress(fp, read_size, read_so_far, size):
            while not queue_to_worker.empty():
                msg, data = queue_to_worker.get()
                queue_to_worker.task_done()

                if msg == progress.REQUEST_CANCEL:
                    raise PrevizCancelUploadException

            data = ('progress', read_so_far / size)
            msg = (progress.TASK_UPDATE, data)
            queue_to_main.put(msg)

        try:
            p = previz.PrevizProject(api_root, api_token, project_id)

            url = p.scene(scene_id, include=[])['jsonUrl']
            with export_path.open('rb') as fd:
                p.update_scene(url, fd, on_progress)

            msg = (progress.TASK_DONE, None)
            queue_to_main.put(msg)

        except PrevizCancelUploadException:
            queue_to_main.put((progress.RESPOND_CANCELED, None))

        except Exception:
            msg = (progress.TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == progress.RESPOND_CANCELED:
                    self.finished_time = time.time()
                    self.state = 'Canceled'
                    self.status = progress.CANCELED
                    self.notify()

                if msg == progress.TASK_DONE:
                    self.progress = 1
                    self.done()

                if msg == progress.TASK_UPDATE:
                    request, data = data

                    if request == 'progress':
                        if self.notify_progress:
                            self.last_progress_notify_date = time.time()
                            self.progress = data
                            self.notify()

                if msg == progress.TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()

        if self.is_finished:
            self.cleanup(context)

    @property
    def notify_progress(self):
        return self.last_progress_notify_date is None \
               or (time.time() - self.last_progress_notify_date) > .25


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

    def __init__(self):
        utils.BackgroundTasksOperator.__init__(self)

        self.g = {}

    @classmethod
    def poll(cls, context):
        return True # Context check in the future

    @log_execute
    def execute(self, context):
        team_uuid = active.team(context)['id']
        #p = previz.PrevizProject(self.api_root, self.api_token)
        #project = p.new_project(self.project_name, team_uuid)
        #refresh_active(context)
        #active.set_project(context, project)
        fileno, path = tempfile.mkstemp(
            suffix = '.json',
            prefix = self.__class__.__name__,
            dir = bpy.context.user_preferences.filepaths.temporary_directory)

        export_path = pathlib.Path(path)

        task = PublishSceneTask(
            api_root = self.api_root,
            api_token = self.api_token,
            project_id = self.project_id,
            scene_id = self.scene_id,
            export_path = export_path,
            debug_cleanup = False
        )
        progress.tasks_runner.add_task(context, task)

        return {'FINISHED'}


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


class CreateProjectTask(progress.Task):
    def __init__(self, **kwargs):
        progress.Task.__init__(self)

        self.label = 'New project'

        self.api_root = kwargs['api_root']
        self.api_token = kwargs['api_token']

        self.project = None

        self.queue_to_worker = queue.Queue()
        self.queue_to_main = queue.Queue()

        self.thread = threading.Thread(target=CreateProjectTask.thread_run,
                                       args=(self.queue_to_worker,
                                             self.queue_to_main),
                                       kwargs=kwargs)

    def run(self, context):
        super().run(context)

        self.progress = 0
        self.notify()

        self.thread.start()

    @staticmethod
    def thread_run(queue_to_worker, queue_to_main, api_root, api_token, project_name, team_uuid):
        try:
            p = previz.PrevizProject(api_root, api_token)

            data = ('new_project', p.new_project(project_name, team_uuid))
            msg = (progress.TASK_UPDATE, data)
            queue_to_main.put(msg)

            data = ('get_all', p.get_all())
            msg = (progress.TASK_UPDATE, data)
            queue_to_main.put(msg)

            msg = (progress.TASK_DONE, None)
            queue_to_main.put(msg)
        except Exception:
            msg = (progress.TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == progress.TASK_DONE:
                    self.done()

                if msg == progress.TASK_UPDATE:
                    self.notify()

                    request, data = data

                    if request == 'new_project':
                        self.project = data

                    if request == 'get_all':
                        active.teams = extract_all(data)
                        active.set_project(context, self.project)

                if msg == progress.TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()


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
        team_uuid = active.team(context)['id']
        #p = previz.PrevizProject(self.api_root, self.api_token)
        #project = p.new_project(self.project_name, team_uuid)
        #refresh_active(context)
        #active.set_project(context, project)

        task = CreateProjectTask(
            api_root = self.api_root,
            api_token = self.api_token,
            project_name = self.project_name,
            team_uuid = team_uuid
        )
        progress.tasks_runner.add_task(context, task)

        return {'FINISHED'}

    @log_invoke
    def invoke(self, context, event):
        self.api_root, self.api_token = previz_preferences(context)
        return context.window_manager.invoke_props_dialog(self)


class CreateSceneTask(progress.Task):
    def __init__(self, **kwargs):
        progress.Task.__init__(self)

        self.label = 'New scene'

        self.api_root = kwargs['api_root']
        self.api_token = kwargs['api_token']

        self.scene = None

        self.queue_to_worker = queue.Queue()
        self.queue_to_main = queue.Queue()

        self.thread = threading.Thread(target=CreateSceneTask.thread_run,
                                       args=(self.queue_to_worker,
                                             self.queue_to_main),
                                       kwargs=kwargs)

    def run(self, context):
        super().run(context)

        self.progress = 0
        self.notify()

        self.thread.start()

    @staticmethod
    def thread_run(queue_to_worker, queue_to_main, api_root, api_token, scene_name, project_id):
        try:
            p = previz.PrevizProject(api_root, api_token, project_id)

            data = ('new_scene', p.new_scene(scene_name))
            msg = (progress.TASK_UPDATE, data)
            queue_to_main.put(msg)

            data = ('get_all', p.get_all())
            msg = (progress.TASK_UPDATE, data)
            queue_to_main.put(msg)

            msg = (progress.TASK_DONE, None)
            queue_to_main.put(msg)
        except Exception:
            msg = (progress.TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == progress.TASK_DONE:
                    self.done()

                if msg == progress.TASK_UPDATE:
                    self.notify()

                    request, data = data

                    if request == 'new_scene':
                        self.scene = data

                    if request == 'get_all':
                        active.teams = extract_all(data)
                        active.set_scene(context, self.scene)

                if msg == progress.TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()


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
        task = CreateSceneTask(
            api_root = self.api_root,
            api_token = self.api_token,
            scene_name = self.scene_name,
            project_id = active.project(context)['id']
        )
        progress.tasks_runner.add_task(context, task)

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
        
        active_scene_is_valid = active.is_valid(context)
        
        return is_valid_image and api_root_is_valid and api_token_is_valid and active_scene_is_valid

    def build_tasks(self, context):
        filepath = pathlib.Path(self.filepath)
        tasks = [
            {'func': self.build_task_upload(
                        self.api_root,
                        self.api_token,
                        self.project_id,
                        filepath
                    )},
            {'func': self.build_task_done_message(filepath)},
        ]
        return tasks

    def build_task_upload(self, api_root, api_token, project_id, filepath):
        def task():
            def progress_callback(encoder):
                print('Uploading {} {} / {}'.format(str(filepath), encoder.bytes_read, encoder.len))
            p = previz.PrevizProject(api_root, api_token, project_id)
            with filepath.open('rb') as fd:
                p.upload_asset(filepath.name, fd, progress_callback)
        return task

    def build_task_done_message(self, filepath):
        def task():
            self.report({'INFO'}, 'Previz: Uploaded asset {!s}'.format(filepath))
        return task

    def task_done(self, result):
        pass

    def task_args(self):
        return (), {}

    def cancel(self, context):
        self.report({'INFO'}, 'Previz: Asset {} export cancelled'.format(self.filepath))
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
        self.project_id = active.project(context)['id']

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


active = Active()
new_plugin_version = None

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

def refresh_active(context):
    api_root, api_token = previz_preferences(context)
    p = previz.PrevizProject(api_root, api_token)
    active.teams = extract_all(p.get_all())
    global new_plugin_version
    new_plugin_version = p.updated_plugin('blender', version_string)


class RefreshProjects(bpy.types.Operator):
    bl_idname = 'export_scene.previz_refresh_projects'
    bl_label = 'Refresh Previz projects'

    @classmethod
    def poll(cls, context):
        api_root, api_token = previz_preferences(context)
        return len(api_root) > 0 and len(api_token) > 0

    @log_execute
    def execute(self, context):
        api_root, api_token = previz_preferences(context)
        task = RefreshAllTask(api_root, api_token, version_string)
        progress.tasks_runner.add_task(context, task)
        return {'FINISHED'}


class RefreshAllTask(progress.Task):
    def __init__(self, api_root, api_token, version_string):
        progress.Task.__init__(self)

        self.label = 'Refresh'

        self.queue_to_worker = queue.Queue()
        self.queue_to_main = queue.Queue()
        self.thread = threading.Thread(target=RefreshAllTask.thread_run,
                                       args=(self.queue_to_worker,
                                             self.queue_to_main,
                                             api_root,
                                             api_token,
                                             version_string))

    def run(self, context):
        super().run(context)

        self.progress = 0
        self.notify()

        self.thread.start()

    @staticmethod
    def thread_run(queue_to_worker, queue_to_main, api_root, api_token, version_string):
        try:
            p = previz.PrevizProject(api_root, api_token)

            data = ('get_all', p.get_all())
            msg = (progress.TASK_UPDATE, data)
            queue_to_main.put(msg)

            data = ('updated_plugin', p.updated_plugin('blender', version_string))
            msg = (progress.TASK_UPDATE, data)
            queue_to_main.put(msg)

            msg = (progress.TASK_DONE, None)
            queue_to_main.put(msg)
        except Exception:
            msg = (progress.TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == progress.TASK_DONE:
                    self.done()

                if msg == progress.TASK_UPDATE:
                    self.progress += .5
                    self.notify()

                    request, data = data

                    if request == 'get_all':
                        active.teams = extract_all(data)

                    if request == 'updated_plugin':
                        global new_plugin_version
                        new_plugin_version = data

                if msg == progress.TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()


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

def menu_image_upload(self, context):
    self.layout.operator(UploadImage.bl_idname, text="Upload image to Previz")

def register():
    bpy.utils.register_class(ExportPreviz)
    bpy.utils.register_class(ExportPrevizFromUI)
    bpy.utils.register_class(ExportPrevizFile)
    bpy.utils.register_class(RefreshProjects)
    bpy.utils.register_class(CreateProject)
    bpy.utils.register_class(CreateScene)
    #bpy.utils.register_class(UploadImage)

    bpy.utils.register_class(PrevizPreferences)

    bpy.utils.register_class(PrevizPanel)

    bpy.types.INFO_MT_file_export.append(menu_export)
    #bpy.types.IMAGE_MT_image.append(menu_image_upload)

    progress.register()

def unregister():
    bpy.utils.unregister_class(ExportPreviz)
    bpy.utils.unregister_class(ExportPrevizFromUI)
    bpy.utils.unregister_class(ExportPrevizFile)
    bpy.utils.unregister_class(RefreshProjects)
    bpy.utils.unregister_class(CreateProject)
    bpy.utils.unregister_class(CreateScene)
    #bpy.utils.unregister_class(UploadImage)

    bpy.utils.unregister_class(PrevizPreferences)

    bpy.utils.unregister_class(PrevizPanel)

    bpy.types.INFO_MT_file_export.remove(menu_export)
    #bpy.types.IMAGE_MT_image.remove(menu_image_upload)

    progress.unregister()
