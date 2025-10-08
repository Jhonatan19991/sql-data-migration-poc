"""
Configuración de logging para el sistema de migración
"""

import logging
import os
from django.conf import settings

def setup_logging():
    """Configurar logging para el sistema"""
    
    # Crear directorio de logs si no existe
    log_dir = os.path.join(settings.BASE_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Configuración de logging
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
                'style': '{',
            },
            'simple': {
                'format': '{levelname} {message}',
                'style': '{',
            },
        },
        'handlers': {
            'file': {
                'level': 'INFO',
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': os.path.join(log_dir, 'migration.log'),
                'maxBytes': 1024*1024*5,  # 5 MB
                'backupCount': 5,
                'formatter': 'verbose',
            },
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
            },
            'error_file': {
                'level': 'ERROR',
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': os.path.join(log_dir, 'error.log'),
                'maxBytes': 1024*1024*5,  # 5 MB
                'backupCount': 5,
                'formatter': 'verbose',
            },
        },
        'loggers': {
            'data_migration': {
                'handlers': ['file', 'console', 'error_file'],
                'level': 'INFO',
                'propagate': False,
            },
            'dlt': {
                'handlers': ['file', 'console'],
                'level': 'INFO',
                'propagate': False,
            },
            'django': {
                'handlers': ['file', 'console'],
                'level': 'INFO',
                'propagate': False,
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'WARNING',
        },
    }
    
    return logging_config
