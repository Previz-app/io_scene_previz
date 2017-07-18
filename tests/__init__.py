import itertools
import time
import unittest

import addon_utils
import bpy
import mathutils

import io_scene_dnb_previz
from io_scene_dnb_previz import *
from io_scene_dnb_previz.utils import *
from io_scene_dnb_previz.three_js_exporter import *

from .utils import *

EXPORT_DIRNAME = 'export_tmpdir'

mkdtemp = MakeTempDirectories('unittests-'+io_scene_dnb_previz.__name__)

apidecs = build_api_decorators()

class TestUnittestFramework(unittest.TestCase):
    @scene('test_unittest_framework_1.blend')
    def test_unittest_framework_1(self, scenepath):
        self.assertListEqual(object_names(), ['Camera', 'Lamp', 'Suzanne1'])

    @scene('test_unittest_framework_2.blend')
    def test_unittest_framework_2(self, scenepath):
        self.assertListEqual(object_names(), ['Camera', 'Lamp', 'Suzanne2'])


class TestTasksRunner(unittest.TestCase):
    @mkdtemp
    def test_run(self, tmpdir):
        def dircontent(path):
            return sorted([x.name for x in path.iterdir()])

        def touch(name, duration):
            time.sleep(duration)
            with (tmpdir/name).open('w') as f:
                f.write(name)

        duration = .1

        tasks = queue.Queue()

        tasks.put({'func': touch,
                   'args': ('00_mp1', duration)})

        tasks.put({'func': touch,
                   'args': ('01_sp1', duration),
                   'run_in_subprocess': True})

        tasks.put({'func': touch,
                   'args': ('02_mp2', duration)})

        tasks.put({'func': touch,
                   'args': ('03_sp2', duration),
                   'run_in_subprocess': True})

        tasks.put({'func': touch,
                   'args': ('04_sp3', duration),
                   'run_in_subprocess': True})

        tasks.put({'func': touch,
                   'args': ('05_mp3', duration)})

        tasks.put({'func': touch,
                   'args': ('06_sp4', .2),
                   'run_in_subprocess': True})

        with TaskRunner() as runner:
            while not tasks.empty():
                try:
                    task = tasks.get()
                    runner.run(**task)
                except queue.Empty:
                    break

                while runner.is_working:
                    time.sleep(duration)

                while not runner.has_result:
                    time.sleep(.01)

                runner.pop_result()

        self.assertListEqual(['00_mp1', '01_sp1', '02_mp2', '03_sp2', '04_sp3', '05_mp3', '06_sp4'],
                             dircontent(tmpdir))

    def test_raise(self):
        def raises():
            1/0

        with TaskRunner() as t:
            t.run(func=raises, run_in_subprocess=False)
            with self.assertRaises(ZeroDivisionError):
                t.pop_result()

            t.run(func=raises, run_in_subprocess=True)
            with self.assertRaises(ZeroDivisionError):
                t.pop_result()


class TestDecorators(unittest.TestCase):
    @apidecs.project('8d9e684f-0763-4756-844b-d0219a4f3f9a')
    @apidecs.scene('5a56a895-46ef-4f0f-862c-38ce14f6275b')
    def test_get(self, project, scene):
        self.assertEqual(project['id'], '8d9e684f-0763-4756-844b-d0219a4f3f9a')
        self.assertEqual(scene['id'], '5a56a895-46ef-4f0f-862c-38ce14f6275b')

    @apidecs.tempproject()
    @apidecs.tempscene()
    def test_temp(self, project, scene):
        self.assertEqual(project['id'], '8d9e684f-0763-4756-844b-d0219a4f3f9a')
        self.assertEqual(scene['id'], '5a56a895-46ef-4f0f-862c-38ce14f6275b')


class TestPlugin(unittest.TestCase):
    @scene('test_exporter.blend')
    @mkdtemp
    @apidecs.tempproject()
    @apidecs.tempscene()
    def test_run_export(self, tmpdir, scenepath, project, scene):
        debug_tmpdir = tmpdir/EXPORT_DIRNAME
        self.assertEqual(
            run_previz_exporter(
                project_id=project['id'],
                scene_id=scene['id'],
                debug_run_api_requests=False,
                debug_tmpdir=debug_tmpdir),
            {'FINISHED'})


#class TestApi(unittest.TestCase):
    #@scene('test_assets.blend')
    #@mkdtemp
    #def test_run_export(self, tmpdir, scenepath):
        #project_id = run_create_project(random_project_name())

        #export_dir = tmpdir / EXPORT_DIRNAME
        #self.assertIn(run_previz_exporter(export_dir,
                                          #debug_run_api_requests=True,
                                          #project_id=project_id), [{'FINISHED'}, {'RUNNING_MODAL'}])
        #delete_project(project_id)


class TestThreeJSExporter(unittest.TestCase):
    #@scene('test_exporter.blend')
    #@mkdtemp
    #def test_export(self, tmpdir, scenepath):
        #def load(path):
            #with path.open() as fp:
                #s = json.load(fp)
            #uuid = itertools.count()
            #for g in s['geometries']:
                #g['uuid'] = next(uuid)
            #s['object']['uuid'] = next(uuid)
            #for o in s['object']['children']:
                #o['geometry'] = next(uuid)
                #o['uuid'] = next(uuid)
            #return s

        #export_path = tmpdir / 'test_export.json'
        #with export_path.open('w') as fp:
            #previz.export(build_scene(bpy.context), fp)

        #self.assertEqual(load(export_path),
                         #load(scenepath.with_suffix('.json')))

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
