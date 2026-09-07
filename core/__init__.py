"""`core` is the Django app. Job scripts (blog.py, crawl_site.py) import it from a plain
`python script.py` process, so configure Django on first import when nobody else has.
Worker processes never start the scheduler - that's the server's job."""
import os

from django.conf import settings

if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "presspilot.settings")
    os.environ.setdefault("PRESSPILOT_WORKER", "1")
    import django

    django.setup()
