from django.shortcuts import render
from django.urls import resolve
from django.urls.exceptions import Resolver404
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
                return render(request, 'access_denied.html', {
                    'message': "You don't have a role assigned.",
                }, status=403)

            role = user_role.role
            if not role:
                return render(request, 'access_denied.html', {
                    'message': "You don't have a role assigned.",
                }, status=403)

            permissions = role.permissions
            current_path = request.path_info

            try:
                match = resolve(current_path)
                current_route_name = match.url_name
            except Resolver404:
                return self.get_response(request)

            if not current_route_name:
                return self.get_response(request)

            for perm in permissions:
                if not perm.is_allowed and perm.route_name == current_route_name:
                    return render(request, 'access_denied.html', {
                        'message': "Access Denied: This route is explicitly denied.",
                    }, status=403)

            for perm in permissions:
                if perm.is_allowed and perm.route_name == current_route_name:
                    return self.get_response(request)

            return render(request, 'access_denied.html', {
                'message': "Access Denied: This route is not allowed.",
            }, status=403)

        finally:
            session.close()