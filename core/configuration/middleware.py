from django.utils import timezone, translation

from .services import get_system_configuration


class UserConfigurationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        configuration = get_system_configuration()
        if request.user.is_authenticated:
            request.session.set_expiry(configuration.session_idle_minutes * 60)
            preference = getattr(request.user, "preferences", None)
            language = preference.language if preference else translation.get_language()
        else:
            preference = None
            language = translation.get_language()
        time_zone = timezone.get_current_timezone_name()
        if configuration.time_zone:
            time_zone = configuration.time_zone
        with timezone.override(time_zone), translation.override(language):
            request.user_preference = preference
            request.system_configuration = configuration
            return self.get_response(request)
