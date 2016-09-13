import math
import queue
import requests
import threading

import bpy
from bpy.props import BoolProperty


class PrevizProject(object):
    endpoints_masks = {
        'projects': '{root}/projects',
        'project':  '{root}/projects/{project_id:d}',
        'scene':    '{root}/projects/{project_id:d}/scene',
        'assets':   '{root}/projects/{project_id:d}/assets',
        'asset':    '{root}/projects/{project_id:d}/assets/{asset_id:d}',
        'state':    '{root}/projects/{project_id:d}/state',
    }

    def __init__(self, token, project_id = None, root='https://previz.online/api'):
        self.token = token

        self.url_elems={
            'root': root,
            'project_id': project_id
        }

    def request(self, *args, **kwargs):
        return requests.request(*args,
                                headers=self.headers,
                                verify=False, # TODO: how to make it work on Mac / Windows ?
                                **kwargs)

    def update_scene(self, fp):
        r = self.request('POST',
                         self.url('scene'),
                         files={'file': fp})
        return r.json()

    def projects(self):
        r = self.request('GET',
                         self.url('projects'))
        return r.json()

    def new_project(self, project_name):
        data = {'title': project_name}
        return self.request('POST',
                            self.url('projects'),
                            data=data).json()

    def delete_project(self):
        self.request('DELETE',
                     self.url('project'))

    def assets(self):
        return self.request('GET',
                            self.url('assets')).json()

    def delete_asset(self, asset_id):
        self.request('DELETE',
                     self.url('asset', asset_id=asset_id))

    def upload_asset(self, fp):
        return self.request('POST',
                            self.url('assets'),
                            files={'file': fp}).json()

    def set_state(self, state):
        data = {'state': state}
        self.request('PUT',
                     self.url('state'),
                     data=data)

    def url(self, mask_name, **url_elems):
        url_elems.update(self.url_elems)
        return self.endpoints_masks[mask_name].format(**url_elems)

    @property
    def headers(self):
        return {'Authorization': 'Bearer {}'.format(self.token)}


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

