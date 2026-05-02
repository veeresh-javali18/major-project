from django.apps import AppConfig


class DetectorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'detector'

    def ready(self):
        import os
        # Prevent scheduler from running multiple times in development with autoreload
        if os.environ.get('RUN_MAIN', None) == 'true':
            from detector import scheduler
            scheduler.start_scheduler()
