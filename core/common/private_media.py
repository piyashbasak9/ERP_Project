from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.utils.text import get_valid_filename


def private_media_response(stored_file, *, content_type, filename, disposition='attachment'):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    file_path = Path(stored_file.storage.path(stored_file.name)).resolve()
    relative_path = file_path.relative_to(media_root).as_posix()
    safe_filename = get_valid_filename(filename).replace('"', '')

    if settings.DEBUG:
        response = FileResponse(stored_file.open('rb'), content_type=content_type)
    else:
        response = HttpResponse(content_type=content_type)
        response['X-Accel-Redirect'] = (
            f'/_private_media/{quote(relative_path, safe="/")}'
        )
    response['Content-Disposition'] = f'{disposition}; filename="{safe_filename}"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
