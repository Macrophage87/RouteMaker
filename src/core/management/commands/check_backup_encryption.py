"""`manage.py check_backup_encryption` - a dry run of the nightly dump's encryption.

It answers "will tonight's dump be taken?" before 07:00 UTC rather than after: it reads the
recipients file the dump reads (`settings.BACKUP_AGE_RECIPIENTS`), refuses the same things the
dump refuses (no file, no recipient, a private key in it, no `age`), and then has `age` encrypt
a few bytes to it, so a key `age` itself would not take is caught too. It dumps nothing and
writes nothing, and exits non-zero when tonight's dump would be refused.
"""

from __future__ import annotations

import subprocess
import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from config.procrastinate import backup_recipients_problem


class Command(BaseCommand):
    help = (
        "Check that the nightly dump can be encrypted to the recipients file, without dumping "
        "or writing anything; exit non-zero if it cannot."
    )

    def handle(self, *args, **options) -> None:
        path = settings.BACKUP_AGE_RECIPIENTS
        problem = backup_recipients_problem(path)
        if problem is None:
            probe = subprocess.run(
                ["age", "--encrypt", "--recipients-file", str(path)],
                input=b"routemaker",
                capture_output=True,
                check=False,
            )
            if probe.returncode != 0:
                problem = f"age refused {path}: {probe.stderr.decode(errors='replace').strip()}"
        if problem is not None:
            self.stdout.write(f"refused: the nightly dump would not run: {problem}")
            sys.exit(1)
        self.stdout.write(f"ok: the nightly dump is encrypted to the recipients in {path}")
