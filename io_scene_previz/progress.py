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

    def run(self):
        pass

    def cancel(self):
        pass

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
            row.label(task.label)
            row.label(task.state)
            row.operator('export_scene.previz_cancel_task').task_id = id


def register():
    bpy.utils.register_class(Test)
    bpy.utils.register_class(CancelTask)
    bpy.utils.register_class(Panel)


def unregister():
    bpy.utils.unregister_class(Test)
    bpy.utils.unregister_class(CancelTask)
    bpy.utils.unregister_class(Panel)
