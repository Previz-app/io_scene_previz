import queue
import random
import time
import threading

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

        if len(self.tasks) == 1:
            bpy.ops.export_scene.previz_manage_queue()

        return id

    def tick(self):
        for task in self.tasks.values():
            task.tick()

    @property
    def is_empty(self):
        return len(self.tasks) == 0

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
        for ms in range(0, 510, 100):
            s = ms / 1000
            time.sleep(s)
            self.label = 'task {}'.format(s*2)
            self.progress = s*2
            self.notify()
        self.done()


REQUEST_CANCEL = 0
RESPOND_CANCELLED = 1

class DebugAsyncTask(Task):
    def __init__(self):
        Task.__init__(self)

        self.queue_to_worker = queue.Queue()
        self.queue_to_main = queue.Queue()
        self.thread = threading.Thread(target=DebugAsyncTask.thread_run,
                                       args=(self.queue_to_worker,
                                             self.queue_to_main))

    def run(self):
        print('MAIN: Starting thread')
        self.thread.start()
        print('MAIN: Started thread')

    def cancel(self):
        self.state = 'Cancelling'
        self.status = CANCELLING
        self.notify()
        self.queue_to_worker.put(REQUEST_CANCEL)

    @staticmethod
    def thread_run(queue_to_worker, queue_to_main):
        print('THREAD: Starting')
        i = 0
        while True:
            while not queue_to_worker.empty():
                msg = queue_to_worker.get()
                if msg == REQUEST_CANCEL:
                    queue_to_main.put(RESPOND_CANCELLED)
                    queue_to_worker.task_done()
                    return

            i += 1
            s = random.random()*5
            msg = (i, s)
            queue_to_main.put(msg)
            print('THREAD: Sleep {} {:.2}'.format(*msg))
            time.sleep(s)
        print('THREAD: Stopping')

    def tick(self):
        print('DebugAsyncTask.tick')
        while not self.queue_to_main.empty():
            msg = self.queue_to_main.get()
            print('msg', msg)
            print('is_finished', self.is_finished)

            if not self.is_finished:
                if msg == RESPOND_CANCELLED:
                    self.finished_time = time.time()
                    self.state = 'Cancelled'
                    self.status = CANCELLED
                    self.notify()

                if type(msg) is tuple:
                    self.label = 'Sleep: {} {:.2}'.format(*msg)
                    self.notify()

            self.queue_to_main.task_done()


class Test(bpy.types.Operator):
    bl_idname = 'export_scene.previz_test'
    bl_label = 'Refresh Previz projects'

    def execute(self, context):
        self.report({'INFO'}, 'Previz: progress.Test')
        task = DebugAsyncTask()
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


class ManageQueue(bpy.types.Operator):
    bl_idname = 'export_scene.previz_manage_queue'
    bl_label = 'Manage Previz task queue'

    process_polling_interval = 1 # Needs to be a debug User Preferences flag

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.timer = None

    def execute(self, context):
        print('ManageQueue.execute')
        if tasks_runner.is_empty:
            self.cleanup(context)
            print('ManageQueue.execute FINISHED')
            return {'FINISHED'}
        self.register_timer(context)
        context.window_manager.modal_handler_add(self)
        #tasks_runner.tick()
        print('ManageQueue.execute RUNNING_MODAL')
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            print('ManageQueue.modal CANCELLED')
            return {'CANCELLED'}

        if event.type == 'TIMER':
            return self.handle_timer_event(context, event)

        return {'PASS_THROUGH'}

    def handle_timer_event(self, context, event):
        if tasks_runner.is_empty:
            self.cleanup(context)
            print('ManageQueue.handle_timer_event FINISHED')
            return {'FINISHED'}
        tasks_runner.tick()
        print('ManageQueue.handle_timer_event RUNNING_MODAL')
        return {'RUNNING_MODAL'}

    def cleanup(self, context):
        self.unregister_timer(context)

    def register_timer(self, context):
        if self.timer is None:
            print('ManageQueue.register_timer')
            self.timer = context.window_manager.event_timer_add(self.process_polling_interval, context.window)

    def unregister_timer(self, context):
        if self.timer is not None:
            print('ManageQueue.unregister_timer')
            context.window_manager.event_timer_remove(self.timer)
            self.timer = None


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
    bpy.utils.register_class(ManageQueue)

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
    bpy.utils.unregister_class(ManageQueue)
