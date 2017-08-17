import time

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
        self.on_task_changed = []

    def add_task(self, task):
        id = next(ids)
        task.tasks_runner = self
        self.tasks[id] = task

        task.run()

        return id

    def remove_task(self, task_id):
        task = self.tasks[task_id]
        if not task.is_finished:
            msg = 'Cannot remove unfinished task {!r}'.format(task.label)
            raise RunTimeError(msg)
        del self.tasks[task_id]

    def notify_change(self, task):
        for cb in self.on_task_changed:
            cb(self, task)


tasks_runner = None

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
        self.tasks_runner = None

    def run(self):
        self.state = 'Running'
        self.status = RUNNING
        self.notify()

    def cancel(self):
        self.finished_time = time.time()
        self.state = 'Cancelled'
        self.status = CANCELLED
        self.notify()

    def done(self):
        self.finished_time = time.time()
        self.state = 'Done'
        self.status = DONE
        self.notify()

    @property
    def is_finished(self):
        return self.status in (DONE, CANCELLED, ERROR)

    def tick(self):
        pass

    def notify(self):
        self.tasks_runner.notify_change(self)


class DebugSyncTask(Task):
    def __init__(self):
        Task.__init__(self)

    def run(self):
        super().run()
        for ms in range(0, 1100, 100):
            s = ms / 1000
            time.sleep(s)
            self.label = 'task {}'.format(s)
            self.progress = s
            self.notify()


class Test(bpy.types.Operator):
    bl_idname = 'export_scene.previz_test'
    bl_label = 'Refresh Previz projects'

    def execute(self, context):
        self.report({'INFO'}, 'Previz: progress.Test')
        task = DebugSyncTask()
        tasks_runner.add_task(task)
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
    bl_idname = "SCENE_PT_previz_test"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    cancelled_task_display_timeout = 2 # XXX Needs to be an hidden user property

    def draw(self, context):
        self.layout.operator(
            'export_scene.previz_test',
            text='Progress test'
        )

        self.remove_finished_tasks()

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

    def remove_finished_tasks(self):
        def is_timed_out(task):
            return task.status in (DONE, CANCELLED) \
                and (time.time() - task.finished_time) > self.cancelled_task_display_timeout
        ids = [id for id, task in tasks_runner.tasks.items() if is_timed_out(task)]
        for id in ids:
            tasks_runner.remove_task(id)


def register():
    bpy.utils.register_class(Test)
    bpy.utils.register_class(CancelTask)
    bpy.utils.register_class(RemoveTask)
    bpy.utils.register_class(Panel)

    global tasks_runner
    tasks_runner = TasksRunner()

    def refresh_panel(*args, **kwarsg):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    tasks_runner.on_task_changed.append(refresh_panel)


def unregister():
    bpy.utils.unregister_class(Test)
    bpy.utils.unregister_class(CancelTask)
    bpy.utils.unregister_class(RemoveTask)
    bpy.utils.unregister_class(Panel)
