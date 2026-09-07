import os
import sys

from django.apps import AppConfig

# Management commands that must never spin up cron.
NO_SCHEDULER_COMMANDS = {"migrate", "makemigrations", "test", "shell", "createsuperuser",
                         "collectstatic", "check", "showmigrations"}


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        if os.environ.get("PRESSPILOT_WORKER"):
            return
        if NO_SCHEDULER_COMMANDS & set(sys.argv):
            return
        # runserver forks an autoreloader parent; only the child (RUN_MAIN) serves.
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return
        from core import scheduler

        scheduler.start()
