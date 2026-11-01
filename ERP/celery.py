import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ERP.settings')

app = Celery('ERP')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
