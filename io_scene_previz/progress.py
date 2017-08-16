import addon_utils
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, path_reference_mode


class Test(bpy.types.Operator):
    bl_idname = 'export_scene.previz_test'
    bl_label = 'Refresh Previz projects'

    def execute(self, context):
        self.report({'INFO'}, 'Previz: progress.Test')
        return {'FINISHED'}


class Panel(bpy.types.Panel):
    bl_label = "PrevizProgress"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        self.layout.operator(
            'export_scene.previz_test',
            text='Progress test'
        )


def register():
    bpy.utils.register_class(Test)
    bpy.utils.register_class(Panel)


def unregister():
    bpy.utils.unregister_class(Test)
    bpy.utils.unregister_class(Panel)
