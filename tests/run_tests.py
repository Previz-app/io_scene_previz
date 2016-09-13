import pathlib
import sys

python_path = str(pathlib.Path(__file__).parent.parent)
sys.path.append(python_path)


import tests.__main__
