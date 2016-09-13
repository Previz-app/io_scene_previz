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


class TestPlugin(unittest.TestCase):
    @scene('test_exporter.blend')
    @mkdtemp
    def test_run_export(self, tmpdir, scenepath):
        export_dir = tmpdir/EXPORT_DIRNAME
        self.assertEqual(run_previz_exporter(export_dir), {'FINISHED'})


class TestThreeJSExportPaths(unittest.TestCase):
    @scene('test_assets.blend')
    @mkdtemp
    def test_it(self, tmpdir, scenepath):
        export_dir = tmpdir / EXPORT_DIRNAME
        run_previz_exporter(export_dir)

        p = ThreeJSExportPaths(export_dir)

        self.assertTrue(p.scene.exists())
        self.assertListEqual(sorted([x.name for x in p.assets]), [])


class TestApi(unittest.TestCase):
    @scene('test_assets.blend')
    @mkdtemp
    def test_run_export(self, tmpdir, scenepath):
        project_id = run_create_project(random_project_name())

        export_dir = tmpdir / EXPORT_DIRNAME
        self.assertIn(run_previz_exporter(export_dir,
                                          debug_run_api_requests=True,
                                          project_id=project_id), [{'FINISHED'}, {'RUNNING_MODAL'}])
        delete_project(project_id)


class TestThreeJSExporter(unittest.TestCase):
    def test_UuidBuilder(self):
        b = UuidBuilder()
        self.assertEqual(b('SomeString'), b('SomeString'))
        self.assertEqual(b('SomeString'), b('SomeString').upper())
        self.assertNotEqual(b(), b())

    def test_flat_list(self):
        l = [
            [
                [1, 2, 3],
                [range(4, 6+1), range(7, 9+1)]
            ],
            [
                {
                    (10, 11, 12): 'dummy',
                    13: 'dummy'
                }
            ]
        ]
        self.assertListEqual(flat_list(l),
                             [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])

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
            export(bpy.context, fp)

        self.assertEqual(load(export_path),
                         load(scenepath.with_suffix('.json')))

    def test_color2threejs(self):
        def c(r, g, b):
            return color2threejs(mathutils.Color([r, g, b]))

        self.assertEqual(c(.13, .19, .21), 2175030)
        self.assertEqual(c(.13, 2.47, .21), 2228022)
