import os
import unittest

import tests
from tests.utils import PREVIZ_API_ROOT_ENVVAR, PREVIZ_API_TOKEN_ENVVAR

env_not_set_mask = '\n'.join(
    [
        '\n',
        78*'*',
        'Testing environment not set. Set the variables :',
        '\t-{}'.format(PREVIZ_API_ROOT_ENVVAR),
        '\t-{}'.format(PREVIZ_API_TOKEN_ENVVAR),
        78*'*',
        '\n'
    ]
)

def envvar_is_valid(envvar):
    return len(os.environ.get(envvar, '')) > 0

api_root_is_valid = envvar_is_valid(PREVIZ_API_ROOT_ENVVAR)
api_token_is_valid = envvar_is_valid(PREVIZ_API_TOKEN_ENVVAR)

if  not api_token_is_valid:
    print(env_not_set_mask.format(PREVIZ_API_ROOT_ENVVAR, PREVIZ_API_TOKEN_ENVVAR))
else:
    unittest.main(module=tests, exit=False, argv=[__name__], verbosity=2)
