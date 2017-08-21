import math
import os
import pathlib
import queue
import sys
import threading

import bpy
from bpy.props import BoolProperty


def sitedir():
    path = pathlib.Path(__file__).parent
    if 'VIRTUAL_ENV' in os.environ:
        env = pathlib.Path(os.environ['VIRTUAL_ENV'])
        v = sys.version_info
        path = env / 'lib/python{}.{}/site-packages'.format(v.major, v.minor)
    return str(path.resolve())
