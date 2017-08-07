Previz Blender integration
==========================


Development
-----------

* Create and activate a virtual environment:
``` sh
$ pyvenv-3.5 env
$ source env/bin/activate
(env) $
```
* To use a locally cloned `previz-python-api` repository, `pip install` it as a linked / editable dependencies before installing the other dependencies:
```
(env) $ pip install -e /path/to/previz-python-wrapper
```
* Install the dependencies:
``` sh
(env) $ pip install -r requirements.txt
```
* Link the `io_scene_dnb_previz` module into [an addons folder](https://www.blender.org/manual/en/getting_started/installing/configuration/directories.html#path-layout).
* Run `blender` from the virtual environment. The plugin relies on the `VIRTUAL_ENV` environment variable to find its dependencies
``` sh
(env) $ blender
```
* Activate the plugin in the User Preferences
* Hit F8 to refresh the plugin code


Testing
-------

Unittesting is made with [tox](https://tox.readthedocs.io/en/latest/). Make sure the `blender` executable is in your `PATH`.


Release
-------

`setup.py` defines a `bdist_blender_addon` command that build an addon archive in the `dist` directory.

```sh
# Build from a clean virtual env
$ pyvenv-3.5 env
$ source env/bin/activate

# Install the dependencies
(env) $ pip install -r requirements.txt

# Run [bumpversion](https://github.com/peritus/bumpversion) to update release version
# This will add a new git tag and will commit the new version
# Version types are: major, minor, patch
(env) $ bumpversion patch

# Build the addon archive
(env) $ python setup.py bdist_blender_addon
(env) $ ls dist
