import datetime

import addon_utils
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, path_reference_mode


def id_generator():
    id = -1
    while True:
        id += 1
        yield id
ids = id_generator()


class TasksRunner(object):
    def __init__(self):
        self.tasks = {}

    def add_task(self, task):
        id = next(ids)
        self.tasks[id] = task
        return id

    def remove_task(self, task_id):
        task = self.tasks[task_id]
        if not task.is_finished:
            msg = 'Cannot remove unfinished task {!r}'.format(task.label)
            raise RunTimeError(msg)
        del self.tasks[task_id]

    def run(self):
        pass

tasks_runner = TasksRunner()

IDLE = 'idle'
STARTING = 'starting'
RUNNING = 'running'
DONE = 'done'
CANCELLING = 'cancelling'
CANCELLED = 'cancelled'
ERROR = 'error'


class Task(object):
    def __init__(self):
        self.label = 'label'
        self.status = IDLE
        self.state = 'state'
        self.error = None
        self.progress = None
        self.finished_time = None
        self.is_cancellable = True

    def run(self):
        pass

    def cancel(self):
        self.finished_time = datetime.datetime.now()
        self.state = 'Cancelled'
        self.status = CANCELLED

    @property
    def is_finished(self):
        return self.status in (DONE, CANCELLED, ERROR)

    def tick(self):
        pass


class Test(bpy.types.Operator):
    bl_idname = 'export_scene.previz_test'
    bl_label = 'Refresh Previz projects'

    def execute(self, context):
        self.report({'INFO'}, 'Previz: progress.Test')
        tasks_runner.add_task(Task())
        return {'FINISHED'}


class CancelTask(bpy.types.Operator):
    bl_idname = 'export_scene.previz_cancel_task'
    bl_label = 'Cancel Previz task'

    task_id = IntProperty(
        name = 'Task ID',
        default = -1
    )

    def execute(self, context):
        self.report({'INFO'}, 'Previz: Cancel task {}'.format(self.task_id))
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
        self.report({'INFO'}, 'Previz: Remove task {}'.format(self.task_id))
        tasks_runner.remove_task(self.task_id)
        return {'FINISHED'}


class Panel(bpy.types.Panel):
    bl_label = "PrevizProgress"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        self.layout.operator(
            'export_scene.previz_test',
            text='Progress test'
        )

        for id, task in tasks_runner.tasks.items():
            row = self.layout.row()
            row.label('{} ({})'.format(task.label, task.state))

            if task.is_cancellable and not task.is_finished:
                row.operator(
                    'export_scene.previz_cancel_task',
                    text='',
                    icon='CANCEL').task_id = id

            if task.is_finished:
                row.operator(
                    'export_scene.previz_remove_task',
                    text='',
                    icon='X').task_id = id


def register():
    bpy.utils.register_class(Test)
    bpy.utils.register_class(CancelTask)
    bpy.utils.register_class(RemoveTask)
    bpy.utils.register_class(Panel)


def unregister():
    bpy.utils.unregister_class(Test)
    bpy.utils.unregister_class(CancelTask)
    bpy.utils.unregister_class(RemoveTask)
    bpy.utils.unregister_class(Panel)
