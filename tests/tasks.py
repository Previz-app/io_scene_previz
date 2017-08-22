import random
import time

from io_scene_previz.tasks import *


class TestTask(Task):
    def __init__(self,
            **kwargs):
        Task.__init__(self)

        self.queue_to_worker = queue.Queue()
        self.queue_to_main = queue.Queue()

        self.thread = threading.Thread(target=self.thread_run,
                                       args=(self.queue_to_worker,
                                             self.queue_to_main),
                                       kwargs=kwargs)

    def run(self, context):
        super().run(context)

        self.thread.start()

    @staticmethod
    def thread_run(queue_to_worker, queue_to_main, timeout):
        try:
            t0 = time.time()
            while (time.time() - t0) < timeout:
                while not queue_to_worker.empty():
                    msg, data = queue_to_worker.get()
                    queue_to_worker.task_done()

                    if msg == REQUEST_CANCEL:
                        raise PrevizCancelUploadException

                time.sleep(random.random()*.1)

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
                    self.canceled()

                if msg == TASK_DONE:
                    self.done()

                if msg == TASK_ERROR:
                    exc_info = data
                    self.set_error(exc_info)

            self.queue_to_main.task_done()
