SET BLENDER_EXE="C:\Program Files\Blender Foundation\Blender\blender.exe"
SET TESTS_DIR=%~dp0

%BLENDER_EXE% --factory-startup --debug --background --addons io_scene_dnb_previz --python %TESTS_DIR%run_tests.py
