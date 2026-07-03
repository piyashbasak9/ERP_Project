import re
from django.http import HttpResponseForbidden
from .db import SessionLocal
from .models_sa import UserRole

class URLPermissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if request.user.is_superuser or request.user.is_staff:
            return self.get_response(request)


        session = SessionLocal()
        try:

            user_role = session.query(UserRole).filter(
                UserRole.user_id == request.user.id
            ).first()

            if not user_role:
                return HttpResponseForbidden("You don't have a role assigned.")

            role = user_role.role
            if not role:
                return HttpResponseForbidden("You don't have a role assigned.")

            permissions = role.permissions
            current_path = request.path_info

            
            for perm in permissions:
                if not perm.is_allowed and re.search(perm.url_pattern, current_path):
                    return HttpResponseForbidden("Access Denied: This URL is explicitly denied.")

            
            for perm in permissions:
                if perm.is_allowed and re.search(perm.url_pattern, current_path):
                    return self.get_response(request)

            
            return HttpResponseForbidden("Access Denied: This URL is not allowed.")

        finally:
            session.close()