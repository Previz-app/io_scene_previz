import os
from pathlib import Path
import sys


# Add path for modules installed by pip

if 'VIRTUAL_ENV' in os.environ:
    major, minor = sys.version_info.major, sys.version_info.minor
    python = 'python{major}.{minor}'.format(major=major, minor=minor)
    envroot = Path(os.environ['VIRTUAL_ENV'])
    env_site_packages = envroot / 'lib' / python / 'site-packages'
    sys.path.append(str(env_site_packages))

import coverage
import nose


# Add blender repo path for tests module

blender_addon_repo_root_path = str(Path(__file__).parent.parent)
sys.path.append(blender_addon_repo_root_path)

from tests import PREVIZ_API_ROOT_ENVVAR, PREVIZ_API_TOKEN_ENVVAR


def error_message():
    return '\n'.join(
        [
            '\n',
            78*'*',
            'Testing environment not set. Set the variables :',
            '\t- {}'.format(PREVIZ_API_ROOT_ENVVAR),
            '\t- {}'.format(PREVIZ_API_TOKEN_ENVVAR),
            78*'*',
            '\n'
        ]
    )

def is_environment_valid():
    def envvar_is_valid(envvar):
        return len(os.environ.get(envvar, '')) > 0
    
    return envvar_is_valid(PREVIZ_API_ROOT_ENVVAR) \
       and envvar_is_valid(PREVIZ_API_TOKEN_ENVVAR)

def main():
    cov = coverage.coverage()
    cov.start()
    nose.run(argv=[__file__])
    cov.stop()
    cov.save()

if __name__ == '__main__':
    if not is_environment_valid():
        print(error_message())
        raise EnvironmentError
    main()
