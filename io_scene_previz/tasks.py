import datetime
import getpass
import platform
import queue
import sys
import time
import threading
import traceback

import bpy
from bpy.props import IntProperty

import pyperclip

import previz

from . import three_js_exporter

def id_generator():
    id = -1
    while True:
        id += 1
        yield id


class TasksRunner(object):
    def __init__(self, keep_finished_task_timeout = 2):
        self.keep_finished_task_timeout = keep_finished_task_timeout

        self.tasks = {}
        self.on_task_changed = []

        self.id_generator = id_generator()

    def add_task(self, context, task):
        id = self.new_task_id()
        task.tasks_runner = self
        self.tasks[id] = task

        task.run(context)

        if len(self.tasks) == 1:
            bpy.ops.export_scene.previz_manage_queue()

        return id

    def tick(self, context):
        for task in self.tasks.values():
            task.tick(context)
        self.remove_finished_tasks()

    def cancel(self):
        for task in [t for t in self.tasks.values() if t.is_cancelable]:
            task.cancel()

    def remove_finished_tasks(self):
        def is_timed_out(task):
            return task.status in (DONE, CANCELED) \
                   and (time.time() - task.finished_time) > self.keep_finished_task_timeout
        ids = [id for id, task in self.tasks.items() if is_timed_out(task)]
        for id in ids:
            self.remove_task(id)
            self.notify_change(None)

    @property
    def is_empty(self):
        return len(self.tasks) == 0

    def remove_task(self, task_id):
        task = self.tasks[task_id]
        if not task.is_finished:
            msg = 'Cannot remove unfinished task {!r}'.format(task.label)
            raise RuntimeError(msg)
        del self.tasks[task_id]

    def notify_change(self, task):
        for cb in self.on_task_changed:
            cb(self, task)

    def new_task_id(self):
        return next(self.id_generator)


tasks_runner = None

IDLE = 'idle'
STARTING = 'starting'
RUNNING = 'running'
DONE = 'done'
CANCELING = 'canceling'
CANCELED = 'canceled'
ERROR = 'error'


class Task(object):
    def __init__(self):
        self.label = 'label'
        self.status = IDLE
        self.state = 'Idle'
        self.error = None
        self.progress = None
        self.finished_time = None
        self.tasks_runner = None

    def run(self, context):
        self.state = 'Running'
        self.status = RUNNING
        self.notify()

    def canceling(self):
        self.state = 'Canceling'
        self.status = CANCELING
        self.notify()

    def canceled(self):
        self.finished_time = time.time()
        self.state = 'Canceled'
        self.status = CANCELED
        self.notify()

    def done(self):
        self.finished_time = time.time()
        self.state = 'Done'
        self.status = DONE
        self.notify()

    def set_error(self, exc_info):
        self.finished_time = time.time()
        self.error = exc_info
        self.state = 'Error'
        self.status = ERROR
        self.notify()

    @property
    def is_cancelable(self):
        return hasattr(self, 'cancel')

    @property
    def is_finished(self):
        return self.status in (DONE, CANCELED, ERROR)

    def tick(self, context):
        pass

    def notify(self):
        self.tasks_runner.notify_change(self)


REQUEST_CANCEL = 'REQUEST_CANCEL'
RESPOND_CANCELED = 'RESPOND_CANCELED'
TASK_DONE = 'TASK_DONE'
TASK_UPDATE = 'TASK_UPDATE'
TASK_ERROR = 'TASK_ERROR'


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


class RefreshAllTask(Task):
    def __init__(
            self,
            api_root,
            api_token,
            version_string,
            on_get_all,
            on_updated_plugin):
        Task.__init__(self)

        self.on_get_all = on_get_all
        self.on_updated_plugin = on_updated_plugin

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
            msg = (TASK_UPDATE, data)
            queue_to_main.put(msg)

            data = ('updated_plugin', p.updated_plugin('blender', version_string))
            msg = (TASK_UPDATE, data)
            queue_to_main.put(msg)

            msg = (TASK_DONE, None)
            queue_to_main.put(msg)
        except Exception:
            msg = (TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == TASK_DONE:
                    self.done()

                if msg == TASK_UPDATE:
                    self.progress += .5
                    self.notify()

                    request, data = data

                    if request == 'get_all':
                        self.on_get_all(context, data)

                    if request == 'updated_plugin':
                        self.on_updated_plugin(context, data)

                if msg == TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()


class CreateProjectTask(Task):
    def __init__(self,
            on_done,
            **kwargs):
        Task.__init__(self)

        self.on_done = on_done

        self.label = 'New project'

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
            msg = (TASK_UPDATE, data)
            queue_to_main.put(msg)

            data = ('get_all', p.get_all())
            msg = (TASK_UPDATE, data)
            queue_to_main.put(msg)

            msg = (TASK_DONE, None)
            queue_to_main.put(msg)
        except Exception:
            msg = (TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == TASK_DONE:
                    self.done()

                if msg == TASK_UPDATE:
                    self.notify()

                    request, data = data

                    if request == 'new_project':
                        self.project = data

                    if request == 'get_all':
                        self.on_done(context, data, self.project)

                if msg == TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()


class CreateSceneTask(Task):
    def __init__(self, on_done, **kwargs):
        Task.__init__(self)

        self.on_done = on_done

        self.label = 'New scene'

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
            msg = (TASK_UPDATE, data)
            queue_to_main.put(msg)

            data = ('get_all', p.get_all())
            msg = (TASK_UPDATE, data)
            queue_to_main.put(msg)

            msg = (TASK_DONE, None)
            queue_to_main.put(msg)
        except Exception:
            msg = (TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == TASK_DONE:
                    self.done()

                if msg == TASK_UPDATE:
                    self.notify()

                    request, data = data

                    if request == 'new_scene':
                        self.scene = data

                    if request == 'get_all':
                        self.on_done(context, data, self.scene)

                if msg == TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()


class PrevizCancelUploadException(Exception):
    pass


class PublishSceneTask(Task):
    def __init__(self, debug_cleanup = True, **kwargs):
        Task.__init__(self)

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
        self.queue_to_worker.put((REQUEST_CANCEL, None))

    @staticmethod
    def thread_run(queue_to_worker, queue_to_main, api_root, api_token, project_id, scene_id, export_path):
        def on_progress(fp, read_size, read_so_far, size):
            while not queue_to_worker.empty():
                msg, data = queue_to_worker.get()
                queue_to_worker.task_done()

                if msg == REQUEST_CANCEL:
                    raise PrevizCancelUploadException

            data = ('progress', read_so_far / size)
            msg = (TASK_UPDATE, data)
            queue_to_main.put(msg)

        try:
            p = previz.PrevizProject(api_root, api_token, project_id)

            url = p.scene(scene_id, include=[])['jsonUrl']
            with export_path.open('rb') as fd:
                p.update_scene(url, fd, on_progress)

            msg = (TASK_DONE, None)
            queue_to_main.put(msg)

        except PrevizCancelUploadException:
            queue_to_main.put((RESPOND_CANCELED, None))

        except Exception:
            msg = (TASK_ERROR, sys.exc_info())
            queue_to_main.put(msg)

    def tick(self, context):
        while not self.queue_to_main.empty():
            msg, data = self.queue_to_main.get()

            if not self.is_finished:
                if msg == RESPOND_CANCELED:
                    self.finished_time = time.time()
                    self.state = 'Canceled'
                    self.status = CANCELED
                    self.notify()

                if msg == TASK_DONE:
                    self.progress = 1
                    self.done()

                if msg == TASK_UPDATE:
                    request, data = data

                    if request == 'progress':
                        if self.notify_progress:
                            self.last_progress_notify_date = time.time()
                            self.progress = data
                            self.notify()

                if msg == TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()

        if self.is_finished:
            self.cleanup(context)

    @property
    def notify_progress(self):
        return self.last_progress_notify_date is None \
               or (time.time() - self.last_progress_notify_date) > .25



class ManageQueue(bpy.types.Operator):
    bl_idname = 'export_scene.previz_manage_queue'
    bl_label = 'Manage Previz task queue'

    process_polling_interval = 1 # Needs to be a debug User Preferences flag

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.timer = None

    def execute(self, context):
        if tasks_runner.is_empty:
            self.cleanup(context)
            return {'FINISHED'}
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


class Panel(bpy.types.Panel):
    bl_label = "PrevizProgress"
    bl_idname = "SCENE_PT_previz_test"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        for id, task in tasks_runner.tasks.items():
            row = self.layout.row()
            label = '{} ({})'.format(task.label, task.state)
            if task.progress is not None:
                label += ' {:.0f}%'.format(task.progress*100)
            row.label(label, icon='RIGHTARROW_THIN')

            if task.status == ERROR:
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
                icon = 'FILE_TICK' if task.status == DONE else 'X'
                row.operator(
                    'export_scene.previz_remove_task',
                    text='',
                    icon=icon).task_id = id

            row.enabled = task.status != CANCELING


def register():
    bpy.utils.register_class(CancelTask)
    bpy.utils.register_class(RemoveTask)
    bpy.utils.register_class(Panel)
    bpy.utils.register_class(ManageQueue)
    bpy.utils.register_class(ShowTaskError)

    global tasks_runner
    tasks_runner = TasksRunner()

    def refresh_panel(*args, **kwarsg):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    tasks_runner.on_task_changed.append(refresh_panel)


def unregister():
    global tasks_runner
    tasks_runner.cancel()
    tasks_runner = None

    bpy.utils.unregister_class(CancelTask)
    bpy.utils.unregister_class(RemoveTask)
    bpy.utils.unregister_class(Panel)
    bpy.utils.unregister_class(ManageQueue)
    bpy.utils.unregister_class(ShowTaskError)
