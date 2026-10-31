from django.core.management.base import BaseCommand

from core.notifications.services import run_notification_job


class Command(BaseCommand):
    help = "Generate and send branch-scoped notifications."

    def handle(self, *args, **options):
        result = run_notification_job()
        self.stdout.write(
            self.style.SUCCESS(
                "Notification job completed: "
                f"{result['generated']} generated, {result['sent']} sent, "
                f"{result['failed']} failed."
            )
        )
