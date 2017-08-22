#!/bin/bash

TESTS_DIR=`dirname ${BASH_SOURCE[0]}`

blender --factory-startup --debug --background --addons io_scene_previz --python $TESTS_DIR/run_tests.py

