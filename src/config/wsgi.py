"""The WSGI entry point gunicorn serves.

`settings.WSGI_APPLICATION` has always named `config.wsgi.application` and the
api image's default command is `gunicorn config.wsgi:application`, but the
module itself was never written: the api container exited at start with
`ModuleNotFoundError: No module named 'config.wsgi'`. Nothing else in the stack
noticed, because `worker`, `migrate` and `rebuild` run `./manage.py` and set
Django up through `manage.py`'s own settings default.

PLAN.md:64 - "the API runs under gunicorn with a worker count set from the
host's cores". The worker count is the entrypoint's business; this module is
only the callable those workers load.
"""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
