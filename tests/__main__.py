import os
import unittest

import tests
import tests.utils

env_not_set_mask = '\n'.join(
    [
        '\n',
        78*'*',
        'Testing environment not set. Set the variables :\n - {}',
        78*'*',
        '\n'
    ]
)

api_token_is_valid = len(os.environ.get(tests.utils.PREVIZ_API_TOKEN_ENVVAR, '')) > 0

if  not api_token_is_valid:
    print(env_not_set_mask.format(tests.utils.PREVIZ_API_TOKEN_ENVVAR))
else:
    unittest.main(module=tests, exit=False, argv=[__name__], verbosity=2)
