#!/bin/bash

TESTS_DIR=`dirname ${BASH_SOURCE[0]}`

blender --factory-startup --debug --background --python $TESTS_DIR/run_tests.py

