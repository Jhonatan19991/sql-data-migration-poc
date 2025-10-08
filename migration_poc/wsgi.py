"""
WSGI config for migration_poc project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'migration_poc.settings')

application = get_wsgi_application()
