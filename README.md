dnd Previz Blender integration
==============================


Testing
-------

Unittesting is made with [tox](https://tox.readthedocs.io/en/latest/). Make sure the `blender` executable is in your `PATH`.


Development
-----------

* Link the `io_scene_dnb_previz` module into [an addons folder](https://www.blender.org/manual/en/getting_started/installing/configuration/directories.html#path-layout).
* Activate the plugin in the User Preferences
* Hit F8 to refresh the plugin code


Release
-------

Copy the `previz` module the `io_scene_dnd_previz folder` and zip that folder. Make sure that no stray __pycache__ files lying around. On Linux:

```sh
$ cd /path/to/repo
$ git clean -f -d -x
$ cd blender
$ grep version io_scene_dnb_previz/__init__.py
    'version': (0, 0, 5),
$ cp -r ../previz/previz/io_scene_dnb_previz
$ zip -r io_scene_dnb_previz-v0.0.5.zip io_scene_dnb_previz
  adding: io_scene_dnb_previz/ (stored 0%)
  adding: io_scene_dnb_previz/utils.py (deflated 74%)
  adding: io_scene_dnb_previz/previz/ (stored 0%)
  adding: io_scene_dnb_previz/previz/__init__.py (deflated 74%)
  adding: io_scene_dnb_previz/three_js_exporter.py (deflated 65%)
  adding: io_scene_dnb_previz/__init__.py (deflated 78%)
```
