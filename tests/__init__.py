import itertools
import time
import unittest

import addon_utils
import bpy
import mathutils

import io_scene_previz
from io_scene_previz import *
from io_scene_previz.utils import *
from io_scene_previz.three_js_exporter import *

from .utils import *

EXPORT_DIRNAME = 'export_tmpdir'

mkdtemp = MakeTempDirectories(io_scene_previz.__name__+'-unittests')

apidecs = build_api_decorators()


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


class TestOperatorManageQueue(unittest.TestCase):
    def test_previz_manage_queue(self):
        self.assertEqual(
            bpy.ops.export_scene.previz_manage_queue(),
            {'FINISHED'}
        )


class TestOperatorExportScene(unittest.TestCase):
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
