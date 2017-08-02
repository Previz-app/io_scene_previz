import math
import os
import pathlib
import queue
import sys
import threading

import bpy
from bpy.props import BoolProperty


class BackgroundTasksOperator(bpy.types.Operator):
    process_polling_interval = 1

    debug_run_modal = BoolProperty(
        name="Run modal",
        default=True,
        options={'HIDDEN'}
    )

    def __init__(self):
        self.timer = None
        self.tasks = queue.Queue()
        self.task_runner = TaskRunner()

    # def build_tasks(self, context):
    #     returns []
    #
    # def task_done(self, result):
    #     self.g.update(result)
    #
    # def task_args(self):
    #     args = (self.g,)
    #     kwargs = {}
    #     return args, kwargs

    def modal(self, context, event):
        if event.type == 'ESC':
            return {'CANCELLED'}

        if event.type == 'TIMER':
            return self.handle_timer_event(context)

        return {'PASS_THROUGH'}

    def handle_timer_event(self, context):
        if self.task_runner.has_result:
            try:
                result = self.task_runner.pop_result()
            except:
                self.cleanup(context)
                raise

            self.task_done(result)

        if self.task_runner.is_working:
            return {'RUNNING_MODAL'}

        if not self.tasks.empty():
            task = self.tasks.get()
            args, kwargs = self.task_args()
            self.task_runner.run(args=args, kwargs=kwargs, **task)
            return {'RUNNING_MODAL'}

        self.cleanup(context)
        return {'FINISHED'}

    def cancel(self, context):
        self.cleanup(context)

    def cleanup(self, context):
        self.unregister_timer(context)
        self.task_runner.stop()

    def execute(self, context):
        for t in self.build_tasks(context):
            self.tasks.put(t)

        self.task_runner.start()

        if self.debug_run_modal:
            return self.execute_modal(context)
        return self.execute_blocking(context)

    def execute_modal(self, context):
        self.register_timer(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def execute_blocking(self, context):
        while not self.tasks.empty():
            try:
                task = self.tasks.get()
                self.task_runner.run(args=(self.g,), **task)
                self.g.update(self.task_runner.pop_result())
            except:
                self.cleanup(context)
                raise
        self.cleanup(context)
        return {'FINISHED'}

    def register_timer(self, context):
        if self.timer is None:
            self.timer = context.window_manager.event_timer_add(self.process_polling_interval, context.window)

    def unregister_timer(self, context):
        if self.timer is not None:
            context.window_manager.event_timer_remove(self.timer)
            self.timer = None


class ThreeJSExportPaths(object):
    def __init__(self, dir, json_basename='export.json'):
        self.dir = dir
        self.json_basename = json_basename

    @property
    def scene(self):
        return self.dir / self.json_basename

    @property
    def assets(self):
        return (x for x in self.dir.iterdir() if x != self.scene)


def is_previz_object(object):
    if object.type == 'MESH':
        for prefix in ['prop_', 'screen_']:
            if object.name.startswith(prefix):
                return True

    if object.type == 'CAMERA':
        return True

    return False


class TaskRunner(object):
    def __init__(self):
        self.queue_is_working = queue.Queue(1)
        self.queue_to_worker = queue.Queue(1)
        self.queue_to_main = queue.Queue(1)
        self.thread = threading.Thread(target=TaskRunner.thread_target,
                                       args=(self.queue_to_worker,
                                             self.queue_to_main,
                                             self.queue_is_working))

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, type, value, traceback):
        self.stop()

    def start(self):
        self.thread.start()

    def stop(self):
        self.queue_to_worker.put(None)
        self.thread.join()

    @property
    def is_working(self):
        return not self.queue_is_working.empty()

    @property
    def has_result(self):
        return not self.queue_to_main.empty()

    def pop_result(self):
        ret = self.queue_to_main.get()
        if issubclass(type(ret), Exception):
            raise ret
        return ret

    def run(self, func, run_in_subprocess=False, args=(), kwargs={}):
        assert self.queue_is_working.empty()
        self.queue_is_working.put(True)

        if run_in_subprocess:
            self.queue_to_worker.put((func, args, kwargs))
        else:
            TaskRunner.run_function(func, args, kwargs, self.queue_to_main, self.queue_is_working)

    @staticmethod
    def run_function(func, args, kwargs, queue_to_main, queue_is_working):
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            result = e

        queue_to_main.put(result)
        assert queue_is_working.get()

    @staticmethod
    def thread_target(queue_to_worker, queue_to_main, queue_is_working):
        while True:
            msg = queue_to_worker.get()

            if msg is None:
                break

            func, args, kwargs = msg
            TaskRunner.run_function(func, args, kwargs, queue_to_main, queue_is_working)


def has_menu_item(items, item):
    try:
        next(i for i in items if i[0] == item[0])
        return True
    except StopIteration:
        return False


def sitedir():
    path = pathlib.Path(__file__).parent
    if 'VIRTUAL_ENV' in os.environ:
        env = pathlib.Path(os.environ['VIRTUAL_ENV'])
        v = sys.version_info
        path = env / 'lib/python{}.{}/site-packages'.format(v.major, v.minor)
    return str(path.resolve())


def append_virtual_env_paths(addon_name):
    def egg_links(dirpath, exclude):
        exclude_path = dirpath / '{}.egg-link'.format(addon_name)
        for p in dirpath.glob('*.egg-link'):
            if p != exclude_path:
                with p.open() as fd:
                    new_path = fd.readline().replace('\n', '')
                    yield new_path

    addon_name = addon_name.replace('_', '-') # eggs are dash-named
    path = pathlib.Path(os.environ['VIRTUAL_ENV'])
    v = sys.version_info
    path /= 'lib/python{}.{}/site-packages'.format(v.major, v.minor)
    sys.path.append(str(path))
    for link in egg_links(path, addon_name):
        sys.path.append(link)


def append_included_modules_paths():
    p = pathlib.Path(__file__).parent
    sys.path.append(str(p))
