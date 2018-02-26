from setuptools import setup, find_packages

from tools.distutils.command import bdist_blender_addon

setup(
    name='io_scene_previz',

    # Versions should comply with PEP440.  For a discussion on single-sourcing
    # the version across setup.py and the project code, see
    # https://packaging.python.org/en/latest/single_source_version.html
    version='1.2.2',
    description='Blender Previz addon',
    url='https://app.previz.co',
    author='Previz',
    author_email='info@previz.co',
    license='MIT',

    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: End Users/Desktop',
        'Topic :: Multimedia :: Graphics :: 3D Modeling',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3 :: Only'
    ],

    keywords='previz 3d scene exporter',
    packages=find_packages(exclude=['tools.distutils.command', 'tests']),
    install_requires=['previz', 'pyperclip', 'requests_toolbelt', 'semantic_version'],
    extras_require={},
    package_data={},
    data_files=[],
    cmdclass={
        'bdist_blender_addon': bdist_blender_addon
    }
)
