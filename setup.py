from setuptools import setup, find_packages

from buildcmds.addon import bdist_blender_addon

setup(
    name='io_scene_previz',

    # Versions should comply with PEP440.  For a discussion on single-sourcing
    # the version across setup.py and the project code, see
    # https://packaging.python.org/en/latest/single_source_version.html
    version='0.0.7',
    description='Blender Previz addon',
    url='https://app.previz.co',
    author='Previz',
    author_email='info@previz.co',
    license='MIT',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Multimedia :: Graphics :: 3D Modeling',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
    ],

    keywords='previz development 3d scene exporter',
    packages=find_packages(exclude=['buildcmds', 'tests']),
    install_requires=['previz'],
    extras_require={},
    package_data={},
    data_files=[],
    cmdclass={
        'bdist_blender_addon': bdist_blender_addon
    }
)
