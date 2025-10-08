"""
Comando para inicializar el sistema de seguridad
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from data_migration.models import APIKey
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Inicializa el sistema de seguridad creando API keys por defecto'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-default-keys',
            action='store_true',
            help='Crear API keys por defecto para desarrollo'
        )
        parser.add_argument(
            '--admin-username',
            type=str,
            default='admin',
            help='Username del admin para crear API key (default: admin)'
        )

    def handle(self, *args, **options):
        create_default_keys = options['create_default_keys']
        admin_username = options['admin_username']
        
        self.stdout.write(
            self.style.SUCCESS('🔐 Inicializando sistema de seguridad...')
        )
        
        # Verificar si existe un superusuario
        if not User.objects.filter(is_superuser=True).exists():
            self.stdout.write(
                self.style.WARNING('⚠️  No se encontró ningún superusuario.')
            )
            self.stdout.write('Ejecuta: python manage.py create_admin_user')
            return
        
        # Crear API keys por defecto si se solicita
        if create_default_keys:
            self.create_default_api_keys(admin_username)
        
        # Mostrar resumen
        self.show_security_summary()

    def create_default_api_keys(self, admin_username):
        """Crea API keys por defecto para desarrollo"""
        try:
            admin_user = User.objects.get(username=admin_username)
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'❌ Usuario admin "{admin_username}" no existe')
            )
            return
        
        # API Key para desarrollo
        if not APIKey.objects.filter(name='Development Key').exists():
            api_key = APIKey.generate_key()
            key_hash = APIKey.hash_key(api_key)
            
            APIKey.objects.create(
                name='Development Key',
                key_hash=key_hash,
                user=admin_user,
                can_ingest=True,
                can_backup=True,
                can_restore=True,
                can_view_logs=True,
                can_trigger_migration=True
            )
            
            self.stdout.write(
                self.style.SUCCESS('✅ API Key de desarrollo creada')
            )
            self.stdout.write(f'   API Key: {api_key}')
        
        # API Key para solo lectura
        if not APIKey.objects.filter(name='Read Only Key').exists():
            api_key = APIKey.generate_key()
            key_hash = APIKey.hash_key(api_key)
            
            APIKey.objects.create(
                name='Read Only Key',
                key_hash=key_hash,
                user=admin_user,
                can_ingest=False,
                can_backup=False,
                can_restore=False,
                can_view_logs=True,
                can_trigger_migration=False
            )
            
            self.stdout.write(
                self.style.SUCCESS('✅ API Key de solo lectura creada')
            )
            self.stdout.write(f'   API Key: {api_key}')
        
        # API Key para ingestión
        if not APIKey.objects.filter(name='Ingestion Key').exists():
            api_key = APIKey.generate_key()
            key_hash = APIKey.hash_key(api_key)
            
            APIKey.objects.create(
                name='Ingestion Key',
                key_hash=key_hash,
                user=admin_user,
                can_ingest=True,
                can_backup=False,
                can_restore=False,
                can_view_logs=False,
                can_trigger_migration=False
            )
            
            self.stdout.write(
                self.style.SUCCESS('✅ API Key de ingestión creada')
            )
            self.stdout.write(f'   API Key: {api_key}')

    def show_security_summary(self):
        """Muestra un resumen del estado de seguridad"""
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('📊 Resumen de Seguridad:'))
        self.stdout.write('')
        
        # Contar superusuarios
        superusers = User.objects.filter(is_superuser=True).count()
        self.stdout.write(f'👑 Superusuarios: {superusers}')
        
        # Contar API keys
        total_keys = APIKey.objects.count()
        active_keys = APIKey.objects.filter(is_active=True).count()
        self.stdout.write(f'🔑 API Keys totales: {total_keys}')
        self.stdout.write(f'🔑 API Keys activas: {active_keys}')
        
        # Mostrar API keys existentes
        if APIKey.objects.exists():
            self.stdout.write('')
            self.stdout.write('📋 API Keys existentes:')
            for key in APIKey.objects.all():
                status = '✅' if key.is_valid() else '❌'
                perms = []
                if key.can_ingest:
                    perms.append('Ingest')
                if key.can_backup:
                    perms.append('Backup')
                if key.can_restore:
                    perms.append('Restore')
                if key.can_view_logs:
                    perms.append('Logs')
                if key.can_trigger_migration:
                    perms.append('Migration')
                
                perms_str = ', '.join(perms) if perms else 'Sin permisos'
                self.stdout.write(f'   {status} {key.name} - {perms_str}')
        
        self.stdout.write('')
        self.stdout.write('🌐 Acceso al panel de administración:')
        self.stdout.write('   http://localhost:8000/admin/')
        self.stdout.write('')
        self.stdout.write('📚 Documentación de seguridad:')
        self.stdout.write('   Ver README.md - Sección "Seguridad de la API"')
