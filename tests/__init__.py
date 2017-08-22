import datetime
import itertools
import time
import unittest

import addon_utils
import bpy
import mathutils

import io_scene_previz
from io_scene_previz import *
from io_scene_previz.tasks import *
from io_scene_previz.utils import *
from io_scene_previz.three_js_exporter import *

from .tasks import *
from .utils import *

bpy.ops.wm.addon_enable(module=io_scene_previz.__name__)

EXPORT_DIRNAME = 'export_tmpdir'

mkdtemp = MakeTempDirectories(io_scene_previz.__name__+'-unittests')

apidecs = build_api_decorators()


def wait_for_queue_to_finish(sleep_time=.1):
    while bpy.ops.export_scene.previz_manage_queue() == {'CANCELLED'}:
            time.sleep(sleep_time)


class TestUnittestFramework(unittest.TestCase):
    @scene('test_unittest_framework_1.blend')
    def test_unittest_framework_1(self, scenepath):
        self.assertListEqual(object_names(), ['Camera', 'Lamp', 'Suzanne1'])

    @scene('test_unittest_framework_2.blend')
    def test_unittest_framework_2(self, scenepath):
        self.assertListEqual(object_names(), ['Camera', 'Lamp', 'Suzanne2'])


class TestDecorators(unittest.TestCase):
    @apidecs.tempproject
    @apidecs.tempscene
    def test_temp(self, project, scene):
        print(project['id'], scene['id'])
        self.assertTrue(len(project['id']) > 0)
        self.assertTrue(len(scene['id']) > 0)


class TestOperators(unittest.TestCase):
    def test_previz_manage_queue(self):
        self.assertEqual(
            bpy.ops.export_scene.previz_manage_queue(),
            {'FINISHED'}
        )

        task = TestTask(timeout=.5)
        task_id = io_scene_previz.tasks_runner.add_task(bpy.context, task)

        wait_for_queue_to_finish()

        self.assertEqual(task.status, DONE)


    def test_previz_cancel_task(self):
        task = TestTask(timeout=10)
        task_id = io_scene_previz.tasks_runner.add_task(bpy.context, task)

        self.assertEqual(
            bpy.ops.export_scene.previz_cancel_task(task_id=task_id),
            {'FINISHED'}
        )

        wait_for_queue_to_finish()

        self.assertEqual(task.status, CANCELED)


    def test_previz_remove_task(self):
        task = TestTask(timeout=.1)
        task_id = io_scene_previz.tasks_runner.add_task(bpy.context, task)

        # XXX How to catch an Exception in an Operator ?
        #self.assertRaises(
            #RuntimeError,
            #bpy.ops.export_scene.previz_remove_task,
            #task_id=task_id
        #)

        time.sleep(.2)
        io_scene_previz.tasks_runner.tick(bpy.context)
        self.assertTrue(task.is_finished)

        self.assertEqual(
            bpy.ops.export_scene.previz_remove_task(task_id=task_id),
            {'FINISHED'}
        )

        self.assertTrue(io_scene_previz.tasks_runner.is_empty)


    def test_previz_show_task_error(self):
        task = TestTask(raise_timeout=.1)
        task_id = io_scene_previz.tasks_runner.add_task(bpy.context, task)

        time.sleep(.2)
        io_scene_previz.tasks_runner.tick(bpy.context)
        self.assertEqual(task.status, ERROR)

        self.assertRaises(
            RuntimeError,
            bpy.ops.export_scene.previz_show_task_error,
            task_id=task_id
        )


    @apidecs.tempproject
    @apidecs.tempscene
    @apidecs.credentials
    def test_previz_refresh(self, api_root, api_token, project, scene):
        bpy.ops.export_scene.previz_refresh(
            api_root=api_root,
            api_token=api_token
        )

        wait_for_queue_to_finish()

        self.assertEqual(
            io_scene_previz.active.project(bpy.context)['id'],
            project['id']
        )
        self.assertEqual(
            io_scene_previz.active.scene(bpy.context)['id'],
            scene['id']
        )


    @apidecs.credentials
    @apidecs.get_team_id
    def test_previz_new_project(self, api_root,  api_token, team_id):
        project_name = datetime.datetime.now().isoformat()
        bpy.ops.export_scene.previz_new_project(
            api_root=api_root,
            api_token=api_token,
            project_name=project_name,
            team_id=team_id
        )

        wait_for_queue_to_finish()

        project = io_scene_previz.active.project(bpy.context)
        self.assertEqual(project['title'], project_name)

        PrevizProject(api_root, api_token, project['id']).delete_project()


    @apidecs.tempproject
    @apidecs.credentials
    def test_previz_new_scene(self, api_root, api_token, project):
        scene_name = datetime.datetime.now().isoformat()
        bpy.ops.export_scene.previz_new_scene(
            api_root=api_root,
            api_token=api_token,
            scene_name=scene_name,
            project_id=project['id']
        )

        wait_for_queue_to_finish()

        scene = io_scene_previz.active.scene(bpy.context)
        self.assertEqual(scene['title'], scene_name)

        PrevizProject(api_root, api_token, project['id']).delete_scene(scene['id'])


    # XXX Doesn't actually test much here as the API wrapper does not allow
    # to retrieve a scene file yet
    @apidecs.credentials
    @apidecs.tempproject
    @apidecs.tempscene
    @scene('test_exporter.blend')
    @mkdtemp
    def test_previz_publish_scene(self, api_root, api_token, project, scene, scenepath, tmpdir):
        debug_export_path = tmpdir/'export.json'
        self.assertEqual(
            bpy.ops.export_scene.previz_publish_scene(
                api_root=api_root,
                api_token=api_token,
                project_id=project['id'],
                scene_id=scene['id'],
                debug_cleanup=False,
                debug_export_path=str(debug_export_path)
            ),
            {'FINISHED'}
        )

        wait_for_queue_to_finish()


    @scene('test_exporter.blend')
    @mkdtemp
    def test_previz_export_scene(self, tmpdir, scenepath):
        filepath = tmpdir/'export.json'
        self.assertEqual(
            bpy.ops.export_scene.previz_export_scene(filepath=str(filepath)),
            {'FINISHED'}
        )
        self.assertTrue(filepath.exists())


class TestThreeJSExporter(unittest.TestCase):
    @scene('test_exporter.blend')
    @mkdtemp
    def test_export(self, tmpdir, scenepath):
        def load(path):
            with path.open() as fp:
                s = json.load(fp)
            uuid = itertools.count()
            for g in s['geometries']:
                g['uuid'] = next(uuid)
            s['object']['uuid'] = next(uuid)
            for o in s['object']['children']:
                o['geometry'] = next(uuid)
                o['uuid'] = next(uuid)
            return s

        export_path = tmpdir / 'test_export.json'
        with export_path.open('w') as fp:
            previz.export(build_scene(bpy.context), fp)

        self.assertEqual(load(export_path),
                         load(scenepath.with_suffix('.json')))

    def test_color2threejs(self):
        def c(r, g, b):
            return color2threejs(mathutils.Color([r, g, b]))

        self.assertEqual(c(.13, .19, .21), 2175030)
        self.assertEqual(c(.13, 2.47, .21), 2228022)


class TestHorizonColor(unittest.TestCase):
    def setUp(self):
        class Object(object):
            pass

        self.context_no_world = Object()
        self.context_no_world.scene = Object()
        self.context_no_world.scene.world = None

        self.context_with_world = Object()
        self.context_with_world.scene = Object()
        self.context_with_world.scene.world = Object()
        self.context_with_world.scene.world.horizon_color = Object()
        self.context_with_world.scene.world.horizon_color.r = .13
        self.context_with_world.scene.world.horizon_color.g = .17
        self.context_with_world.scene.world.horizon_color.b = .19

    def test_horizon_color(self):
        self.assertEqual(horizon_color(self.context_no_world), None)
        self.assertEqual(horizon_color(self.context_with_world), 2173744)
