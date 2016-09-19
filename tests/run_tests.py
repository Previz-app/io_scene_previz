import os
from pathlib import Path
import sys

if 'VIRTUAL_ENV' in os.environ:
    major, minor = sys.version_info.major, sys.version_info.minor
    python = 'python{major}.{minor}'.format(major=major, minor=minor)
    envroot = Path(os.environ['VIRTUAL_ENV'])
    env_site_packages = envroot / 'lib' / python / 'site-packages'
    sys.path.append(str(env_site_packages))

import coverage
import nose

def main():
    python_path = str(Path(__file__).parent.parent)
    sys.path.append(python_path)
    nose.run(argv=[__file__])

if __name__ == '__main__':
    cov = coverage.coverage()
    cov.start()
    main()
    cov.stop()
    cov.save()
