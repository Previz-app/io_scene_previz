SET BLENDER_EXE="C:\Program Files\Blender Foundation\Blender\blender.exe"
SET TESTS_DIR=%~dp0

%BLENDER_EXE% --factory-startup --debug --background --python %TESTS_DIR%run_tests.py
