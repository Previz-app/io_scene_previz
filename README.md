dnd Previz Blender integration
==============================


Scene building conventions
--------------------------

- Screens objects names are prefixed with `screen`. Examples of valid names:
  - `screen`
  - `screenleft`
  - `screenR`
  - `screen_center`
- Props objects names are prefixed with `prop`. Examples of valid names:
  - `prop`
  - `propstage`
  - `propColumnLeft`
  - `prop_column_right`


Development
-----------

* Link the `io_scene_dnb_previz` module into [an addons folder](https://www.blender.org/manual/en/getting_started/installing/configuration/directories.html#path-layout).
* Activate the plugin in the User Preferences
* Hit F8 to refresh the plugin code


Run tests
---------

* Run `tests/run_tests.sh`


Expected Blender three.js exporter parameters
---------------------------------------------

See https://docs.google.com/spreadsheets/d/1Vx759ecdsOL40E1a7ADOzbhsbYe-lMSjdOUxkB3cWRI/edit#gid=461167001.
