import datetime
import getpass
import os
import pathlib
import platform
import site
import sys
import tempfile
import time
import traceback

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, path_reference_mode

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

import pyperclip

import previz
from . import tasks
from . import three_js_exporter
from . import utils


bl_info = {
    'name': "Previz integration",
    'author': "Previz (info@previz.co)",
    'version': (1, 1, 1),
    'blender': (2, 76, 0),
    'location': "File > Export",
    'description': "Upload scenes to Previz.",
    'category': 'Import-Export',
}

version_string = '.'.join([str(x) for x in bl_info['version']])

TEMPORARY_DIRECTORY_PREFIX = 'blender-{}-'.format(__name__)


#############################################################################
# GLOBALS
#############################################################################


active = utils.Active()
new_plugin_version = None
tasks_runner = None


#############################################################################
# QUEUE OPERATORS
#############################################################################


class ManageQueue(bpy.types.Operator):
    bl_idname = 'export_scene.previz_manage_queue'
    bl_label = 'Manage Previz task queue'

    process_polling_interval = .25 # Needs to be a debug User Preferences flag

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.timer = None

    def execute(self, context):
        if tasks_runner.is_empty:
            self.cleanup(context)
            return {'FINISHED'}

        if bpy.app.background:
            tasks_runner.tick(context)
            return {'CANCELLED'}

        self.register_timer(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self.cleanup(context)

    def modal(self, context, event):
        if event.type == 'ESC':
            return {'CANCELED'}

        if event.type == 'TIMER':
            return self.handle_timer_event(context, event)

        return {'PASS_THROUGH'}

    def handle_timer_event(self, context, event):
        if tasks_runner.is_empty:
            self.cleanup(context)
            return {'FINISHED'}
        tasks_runner.tick(context)
        return {'RUNNING_MODAL'}

    def cleanup(self, context):
        tasks_runner.cancel()
        self.unregister_timer(context)

    def register_timer(self, context):
        if self.timer is None:
            self.timer = context.window_manager.event_timer_add(self.process_polling_interval, context.window)

    def unregister_timer(self, context):
        if self.timer is not None:
            context.window_manager.event_timer_remove(self.timer)
            self.timer = None


class CancelTask(bpy.types.Operator):
    bl_idname = 'export_scene.previz_cancel_task'
    bl_label = 'Cancel Previz task'

    task_id = IntProperty(
        name = 'Task ID',
        default = -1
    )

    def execute(self, context):
        tasks_runner.tasks[self.task_id].cancel()
        return {'FINISHED'}


class RemoveTask(bpy.types.Operator):
    bl_idname = 'export_scene.previz_remove_task'
    bl_label = 'Remove Previz task'

    task_id = IntProperty(
        name = 'Task ID',
        default = -1
    )

    def execute(self, context):
        tasks_runner.remove_task(self.task_id)
        return {'FINISHED'}


class ShowTaskError(bpy.types.Operator):
    bl_idname = 'export_scene.previz_show_task_error'
    bl_label = 'Show Previz task error'

    task_id = IntProperty(
        name = 'Task ID',
        default = -1
    )

    def execute(self, context):
        task = tasks_runner.tasks[self.task_id]
        self.report({'ERROR'}, task2report(task))
        debug_info = task2debuginfo(task)
        pyperclip.copy(debug_info)
        print(debug_info)
        return {'FINISHED'}


def task2debuginfo(task):
    type, exception, tb = task.error
    d = datetime.datetime.now()
    d_utc = datetime.datetime.utcfromtimestamp(d.timestamp())
    ret = [
        '---- PREVIZ DEBUG INFO START',
        'Date:    : {}'.format(d.isoformat()),
        'Date UTC : {}'.format(d_utc.isoformat()),
        'User     : {}'.format(getpass.getuser()),
        'Blender  : {}'.format(bpy.app.version_string),
        'OS       : {}'.format(platform.platform()),
        'Python   : {}'.format(sys.version),
        'Addon    : {}'.format(''),
        'Version  : {}'.format(''),
        'Task     : {}'.format(task.label),
        'Status   : {}'.format(task.status),
        'Progress : {}'.format(task.progress),
        'Exception: {}'.format(exception.__class__.__name__),
        'Error    : {}'.format(str(exception)),
        'Traceback:',
        ''
    ]
    ret = '\n'.join(ret) + '\n'
    ret += ''.join(traceback.format_tb(tb))
    ret += '\n---- PREVIZ DEBUG INFO END\n'
    return ret


def task2report(task):
    type, exception, tb = task.error

    return '''Previz task error
Task: {}
Exception: {}
Value: {}

See the console for debug information.

The debug information has been copied to the clipboard.
Please paste it to Previz support.
'''.format(task.label, exception.__class__.__name__, exception)


#############################################################################
# PREVIZ OPERATORS
#############################################################################

default_predicates = {
    str: lambda x: len(x) > 0
}

def set_property_if_invalid(operator, property_name, value, predicate = None):
    current_value = getattr(operator, property_name)
    predicate = predicate if predicate is not None else default_predicates[type(current_value)]
    value_func = value if callable(value) else lambda: value

    if not predicate(current_value):
        setattr(operator, property_name, value_func())


def mkstemp(context, *args, **kwargs):
    return tempfile.mkstemp(
        prefix = __name__ + '-',
        dir = context.user_preferences.filepaths.temporary_directory,
        *args,
        **kwargs
    )


class ApiOperatorMixin:
    api_root = StringProperty(
        name='API root',
        options={'HIDDEN'}
    )

    api_token = StringProperty(
        name='API token',
        options={'HIDDEN'}
    )

    def invoke(self, context, event):
        prefs_api_root, prefs_api_token = previz_preferences(context)
        set_property_if_invalid(self, 'api_root', prefs_api_root)
        set_property_if_invalid(self, 'api_token', prefs_api_token)


class ObjectModeMixin:
    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'


class PublishScene(bpy.types.Operator, ApiOperatorMixin, ObjectModeMixin):
    bl_idname = 'export_scene.previz_publish_scene'
    bl_label = 'Export scene to Previz'

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

    debug_export_path = StringProperty(
        name='Force export path',
        options={'HIDDEN'}
    )

    def execute(self, context):
        # Keep a reference to debug_cleanup so the call back
        # still sees it after the Operator is destroyed
        debug_cleanup = self.debug_cleanup
        def on_done(*args, **kwargs):
            if debug_cleanup and export_path.exists():
                export_path.unlink()

        export_path = pathlib.Path(self.debug_export_path)

        ret = bpy.ops.export_scene.previz_export_scene(
            filepath=str(export_path)
        )
        if 'FINISHED' not in ret:
            on_done()
            return ret

        task = tasks.PublishSceneTask(
            api_root = self.api_root,
            api_token = self.api_token,
            project_id = self.project_id,
            scene_id = self.scene_id,
            export_path = export_path,
            on_done = on_done
        )
        tasks_runner.add_task(context, task)

        return {'FINISHED'}

    def invoke(self, context, event):
        ApiOperatorMixin.invoke(self, context, event)
        set_property_if_invalid(self, 'project_id', active.project(context)['id'])
        set_property_if_invalid(self, 'scene_id', active.scene(context)['id'])
        set_property_if_invalid(self, 'debug_export_path', lambda: mkstemp(context, suffix='.json')[1])
        return self.execute(context)


class ExportScene(bpy.types.Operator, ExportHelper, ObjectModeMixin):
    bl_idname = 'export_scene.previz_export_scene'
    bl_label = 'Export scene to a Previz file'

    filename_ext = ".json"
    filter_glob = StringProperty(
        default="*.json;",
        options={'HIDDEN'},
    )

    # XXX What is path_reference_mode ?
    path_mode = path_reference_mode

    check_extension = True

    def execute(self, context):
        filepath = pathlib.Path(self.as_keywords()['filepath'])
        with filepath.open('w') as fp:
            previz.export(three_js_exporter.build_scene(context), fp)
        return {'FINISHED'}


class RefreshProjects(bpy.types.Operator, ApiOperatorMixin):
    bl_idname = 'export_scene.previz_refresh'
    bl_label = 'Refresh Previz'

    def execute(self, context):
        def on_get_all(context, data):
            active.teams = utils.extract_all(data)

        def on_updated_plugins(context, data):
            global new_plugin_version
            new_plugin_version = data

        task = tasks.RefreshAllTask(
            self.api_root,
            self.api_token,
            version_string,
            on_get_all,
            on_updated_plugins
        )
        tasks_runner.add_task(context, task)
        return {'FINISHED'}

    def invoke(self, context, event):
        ApiOperatorMixin.invoke(self, context, event)
        return self.execute(context)


class CreateProject(bpy.types.Operator, ApiOperatorMixin):
    bl_idname = 'export_scene.previz_new_project'
    bl_label = 'New Previz project'

    project_name = StringProperty(
        name='Project name'
    )

    team_id = StringProperty(
        name='Team UUID',
        options={'HIDDEN'}
    )

    def execute(self, context):
        def on_done(context, data, project):
            active.teams = utils.extract_all(data)
            active.set_project(context, project)

        task = tasks.CreateProjectTask(
            api_root = self.api_root,
            api_token = self.api_token,
            project_name = self.project_name,
            team_uuid = self.team_id,
            on_done = on_done
        )
        tasks_runner.add_task(context, task)

        return {'FINISHED'}

    def invoke(self, context, event):
        ApiOperatorMixin.invoke(self, context, event)
        set_property_if_invalid(self, 'team_id', lambda: active.team(context)['id'])
        return context.window_manager.invoke_props_dialog(self)


class CreateScene(bpy.types.Operator, ApiOperatorMixin):
    bl_idname = 'export_scene.previz_new_scene'
    bl_label = 'New Previz scene'

    scene_name = StringProperty(
        name='Scene name'
    )

    project_id = StringProperty(
        name='Project UUID',
        options={'HIDDEN'}
    )

    def execute(self, context):
        def on_done(context, data, scene):
            active.teams = utils.extract_all(data)
            active.set_scene(context, scene)

        task = tasks.CreateSceneTask(
            api_root = self.api_root,
            api_token = self.api_token,
            scene_name = self.scene_name,
            project_id = self.project_id,
            on_done = on_done
        )
        tasks_runner.add_task(context, task)

        return {'FINISHED'}

    def invoke(self, context, event):
        ApiOperatorMixin.invoke(self, context, event)
        set_property_if_invalid(self, 'project_id', lambda: active.project(context)['id'])
        return context.window_manager.invoke_props_dialog(self)


#############################################################################
# PREFERENCES
#############################################################################


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


def previz_preferences(context):
    prefs = context.user_preferences.addons[__name__].preferences
    return prefs.api_root, prefs.api_token


#############################################################################
# PANELS
#############################################################################


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

    def draw(self, context):
        api_root, api_token = previz_preferences(context)

        if len(api_root) == 0 or len(api_token) == 0:
            self.layout.label('Set the API info in the User Preferences.')
            self.layout.label('Search Previz in the Add-ons tab.')
            self.layout.operator('screen.userpref_show')
            return

        if active.is_refreshed:
            is_team_valid = active.team(context) is not None
            is_project_valid = active.project(context) is not None
            is_scene_valid = active.scene(context) is not None

            row = self.layout.row()
            row.prop(context.scene, 'previz_active_team_id')

            row = self.layout.row()
            row.prop(context.scene, 'previz_active_project_id')
            row.operator('export_scene.previz_new_project', text='', icon='NEW')
            row.enabled = is_team_valid

            row = self.layout.row()
            row.prop(context.scene, 'previz_active_scene_id')
            row.operator('export_scene.previz_new_scene', text='', icon='NEW')
            row.enabled = is_project_valid

            row = self.layout.row()
            row.operator(
                'export_scene.previz_publish_scene',
                text='Publish scene',
                icon='EXPORT'
            )
            row.enabled = is_scene_valid

        self.layout.operator(
            'export_scene.previz_refresh',
            text='Refresh',
            icon='FILE_REFRESH'
        )

        if new_plugin_version:
            text = 'New addon: v' + new_plugin_version['version']
            op = self.layout.operator('wm.url_open', text=text, icon='URL')
            op.url = new_plugin_version['downloadUrl']

        for id, task in tasks_runner.tasks.items():
            row = self.layout.row()
            label = '{} ({})'.format(task.label, task.state)
            if task.progress is not None:
                label += ' {:.0f}%'.format(task.progress*100)
            row.label(label, icon='RIGHTARROW_THIN')

            if task.status == tasks.ERROR:
                row.operator(
                    'export_scene.previz_show_task_error',
                    text='',
                    icon='ERROR').task_id = id

            if task.is_cancelable and not task.is_finished:
                row.operator(
                    'export_scene.previz_cancel_task',
                    text='',
                    icon='CANCEL').task_id = id

            if task.is_finished:
                icon = 'FILE_TICK' if task.status == tasks.DONE else 'X'
                row.operator(
                    'export_scene.previz_remove_task',
                    text='',
                    icon=icon).task_id = id

            row.enabled = task.status != tasks.CANCELING


#############################################################################
# REGISTRATION
#############################################################################


def register_tasks_runner():
    global tasks_runner
    tasks_runner = tasks.TasksRunner()

    def refresh_panel(*args, **kwarsg):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    if not bpy.app.background:
        tasks_runner.on_task_changed.append(refresh_panel)

    def manage_queue(*args, **kwargs):
        bpy.ops.export_scene.previz_manage_queue()
    tasks_runner.on_queue_started.append(manage_queue)


def unregister_tasks_runner():
    global tasks_runner
    tasks_runner.cancel()
    tasks_runner = None


def menu_export(self, context):
    self.layout.operator(ExportScene.bl_idname, text="Previz (three.js .json)")


# TODO To be activated when API endpoint back in API v2
#def menu_image_upload(self, context):
    #self.layout.operator(UploadImage.bl_idname, text="Upload image to Previz")


def register():
    register_tasks_runner()

    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_export.append(menu_export)
    #bpy.types.IMAGE_MT_image.append(menu_image_upload)


def unregister():
    bpy.types.INFO_MT_file_export.remove(menu_export)
    #bpy.types.IMAGE_MT_image.remove(menu_image_upload)

    bpy.utils.unregister_module(__name__)

    unregister_tasks_runner()
