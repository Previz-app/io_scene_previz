import os
from pathlib import Path
import sys


def build_error_message(message):
    """Construct an error string using the given message"""
    return '\n'.join(['\n', 78 * '*', message, 78 * '*', '\n'])


def load_environment_variables():
    """Load environment variables from the .env file"""
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), '.env')
    load_dotenv(dotenv_path=env_path)


def is_virtual_env():
    """Are we running in a virtual environment?"""
    return len(os.environ.get('VIRTUAL_ENV', '')) > 0


def environment_is_valid():
    """Are all of the required environment variables set?"""

    def envvar_is_set(envvar):
        """Does the environment variable with the given name exist?"""
        return len(os.environ.get(envvar, '')) > 0

    return envvar_is_set(ENV_PREVIZ_API_ROOT) \
           and envvar_is_set(ENV_PREVIZ_TEAM_UUID) \
           and envvar_is_set(ENV_PREVIZ_API_TOKEN) \
           and envvar_is_set('VIRTUAL_ENV')


def bootstrap_packages():
    """Append the virtual environment packages to the system path"""
    major, minor = sys.version_info.major, sys.version_info.minor
    python = 'python{major}.{minor}'.format(major=major, minor=minor)
    envroot = Path(os.environ['VIRTUAL_ENV'])
    env_site_packages = envroot / 'lib' / python / 'site-packages'
    sys.path.append(str(env_site_packages))


def main():
    """Run the test suite"""
    import coverage
    import nose

    cov = coverage.coverage()
    cov.start()
    nose.run(argv=[__file__, '--verbosity=2'])
    cov.stop()
    cov.save()


if __name__ == '__main__':
    # Python package importing is appalling.
    # @see https://stackoverflow.com/questions/11536764/how-to-fix-attempted-relative-import-in-non-package-even-with-init-py
    if __package__ is None:
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # It is now safe to assume that Python can find the ``tests`` package
    from tests import ENV_PREVIZ_API_ROOT, ENV_PREVIZ_API_TOKEN, ENV_PREVIZ_TEAM_UUID

    # No point proceeding if we're not running from within a virtual environment, as per the docs
    if not is_virtual_env():
        message = 'You must run this script from a virtual environment.\nSee the README for instructions.'
        print(build_error_message(message))
        raise EnvironmentError

    bootstrap_packages()
    load_environment_variables()

    if not environment_is_valid():
        message = 'Environment variables not configured.\nSee the README for instructions.'
        print(build_error_message(message))
        raise EnvironmentError

    # Finally, we can run the tests
    main()
