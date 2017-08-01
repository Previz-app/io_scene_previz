from distutils.core import Command


class addon(Command):
    description = "Build Blender addon"
    user_options = []

    def initialize_options(self):
        print('addon.initialize_options')

    def finalize_options(self):
        print('addon.finalize_options')

    def run(self):
        print('addon.run')
