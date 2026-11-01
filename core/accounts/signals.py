from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone


@receiver(user_logged_in, dispatch_uid='accounts.set_absolute_session_start')
def set_absolute_session_start(sender, request, user, **kwargs):
    request.session['auth_started_at'] = int(timezone.now().timestamp())
