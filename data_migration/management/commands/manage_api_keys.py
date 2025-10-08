"""
Comando de Django para gestionar API Keys
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from data_migration.models import APIKey
import json


class Command(BaseCommand):
    help = 'Gestiona API Keys para autenticación'

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest='action', help='Acciones disponibles')
        
        # Crear API key
        create_parser = subparsers.add_parser('create', help='Crear nueva API key')
        create_parser.add_argument('name', help='Nombre descriptivo de la API key')
        create_parser.add_argument('--user', help='Usuario asociado (opcional)')
        create_parser.add_argument('--expires-days', type=int, help='Días hasta expiración (opcional)')
        create_parser.add_argument('--can-ingest', action='store_true', default=True, help='Puede usar ingest')
        create_parser.add_argument('--can-backup', action='store_true', default=True, help='Puede crear backups')
        create_parser.add_argument('--can-restore', action='store_true', default=True, help='Puede restaurar')
        create_parser.add_argument('--can-view-logs', action='store_true', default=True, help='Puede ver logs')
        create_parser.add_argument('--can-trigger-migration', action='store_true', default=False, help='Puede disparar migraciones')
        
        # Listar API keys
        list_parser = subparsers.add_parser('list', help='Listar API keys')
        list_parser.add_argument('--active-only', action='store_true', help='Solo mostrar keys activas')
        
        # Desactivar API key
        deactivate_parser = subparsers.add_parser('deactivate', help='Desactivar API key')
        deactivate_parser.add_argument('name', help='Nombre de la API key')
        
        # Activar API key
        activate_parser = subparsers.add_parser('activate', help='Activar API key')
        activate_parser.add_argument('name', help='Nombre de la API key')
        
        # Eliminar API key
        delete_parser = subparsers.add_parser('delete', help='Eliminar API key')
        delete_parser.add_argument('name', help='Nombre de la API key')
        
        # Mostrar detalles
        show_parser = subparsers.add_parser('show', help='Mostrar detalles de API key')
        show_parser.add_argument('name', help='Nombre de la API key')

    def handle(self, *args, **options):
        action = options['action']
        
        if action == 'create':
            self.create_api_key(options)
        elif action == 'list':
            self.list_api_keys(options)
        elif action == 'deactivate':
            self.deactivate_api_key(options)
        elif action == 'activate':
            self.activate_api_key(options)
        elif action == 'delete':
            self.delete_api_key(options)
        elif action == 'show':
            self.show_api_key(options)
        else:
            raise CommandError('Acción no válida. Use --help para ver las opciones disponibles.')

    def create_api_key(self, options):
        """Crear nueva API key"""
        name = options['name']
        
        # Verificar que no exista
        if APIKey.objects.filter(name=name).exists():
            raise CommandError(f'API key "{name}" ya existe')
        
        # Obtener usuario si se especifica
        user = None
        if options['user']:
            try:
                user = User.objects.get(username=options['user'])
            except User.DoesNotExist:
                raise CommandError(f'Usuario "{options["user"]}" no existe')
        
        # Calcular fecha de expiración
        expires_at = None
        if options['expires_days']:
            expires_at = timezone.now() + timedelta(days=options['expires_days'])
        
        # Generar API key
        api_key = APIKey.generate_key()
        key_hash = APIKey.hash_key(api_key)
        
        # Crear objeto
        api_key_obj = APIKey.objects.create(
            name=name,
            key_hash=key_hash,
            user=user,
            expires_at=expires_at,
            can_ingest=options['can_ingest'],
            can_backup=options['can_backup'],
            can_restore=options['can_restore'],
            can_view_logs=options['can_view_logs'],
            can_trigger_migration=options['can_trigger_migration']
        )
        
        self.stdout.write(
            self.style.SUCCESS(f'✓ API key creada exitosamente')
        )
        self.stdout.write(f'Nombre: {name}')
        self.stdout.write(f'API Key: {api_key}')
        self.stdout.write(f'⚠️  IMPORTANTE: Guarda esta API key de forma segura. No se puede recuperar.')
        
        if expires_at:
            self.stdout.write(f'Expira: {expires_at}')

    def list_api_keys(self, options):
        """Listar API keys"""
        queryset = APIKey.objects.all()
        
        if options['active_only']:
            queryset = queryset.filter(is_active=True)
        
        if not queryset.exists():
            self.stdout.write('No hay API keys registradas.')
            return
        
        self.stdout.write(f'{"Nombre":<20} {"Estado":<10} {"Último uso":<20} {"Permisos":<50}')
        self.stdout.write('-' * 100)
        
        for api_key in queryset:
            status = 'Activa' if api_key.is_valid() else 'Inactiva/Expirada'
            last_used = api_key.last_used.strftime('%Y-%m-%d %H:%M') if api_key.last_used else 'Nunca'
            
            permissions = []
            if api_key.can_ingest:
                permissions.append('ingest')
            if api_key.can_backup:
                permissions.append('backup')
            if api_key.can_restore:
                permissions.append('restore')
            if api_key.can_view_logs:
                permissions.append('logs')
            if api_key.can_trigger_migration:
                permissions.append('migration')
            
            perms_str = ', '.join(permissions)
            
            self.stdout.write(f'{api_key.name:<20} {status:<10} {last_used:<20} {perms_str:<50}')

    def deactivate_api_key(self, options):
        """Desactivar API key"""
        name = options['name']
        
        try:
            api_key = APIKey.objects.get(name=name)
            api_key.is_active = False
            api_key.save()
            
            self.stdout.write(
                self.style.SUCCESS(f'✓ API key "{name}" desactivada')
            )
        except APIKey.DoesNotExist:
            raise CommandError(f'API key "{name}" no existe')

    def activate_api_key(self, options):
        """Activar API key"""
        name = options['name']
        
        try:
            api_key = APIKey.objects.get(name=name)
            api_key.is_active = True
            api_key.save()
            
            self.stdout.write(
                self.style.SUCCESS(f'✓ API key "{name}" activada')
            )
        except APIKey.DoesNotExist:
            raise CommandError(f'API key "{name}" no existe')

    def delete_api_key(self, options):
        """Eliminar API key"""
        name = options['name']
        
        try:
            api_key = APIKey.objects.get(name=name)
            api_key.delete()
            
            self.stdout.write(
                self.style.SUCCESS(f'✓ API key "{name}" eliminada')
            )
        except APIKey.DoesNotExist:
            raise CommandError(f'API key "{name}" no existe')

    def show_api_key(self, options):
        """Mostrar detalles de API key"""
        name = options['name']
        
        try:
            api_key = APIKey.objects.get(name=name)
            
            self.stdout.write(f'Detalles de API key: {name}')
            self.stdout.write('-' * 50)
            self.stdout.write(f'Estado: {"Activa" if api_key.is_valid() else "Inactiva/Expirada"}')
            self.stdout.write(f'Usuario: {api_key.user.username if api_key.user else "N/A"}')
            self.stdout.write(f'Creada: {api_key.created_at}')
            self.stdout.write(f'Último uso: {api_key.last_used or "Nunca"}')
            self.stdout.write(f'Expira: {api_key.expires_at or "Nunca"}')
            self.stdout.write('Permisos:')
            self.stdout.write(f'  - Ingest: {"✓" if api_key.can_ingest else "✗"}')
            self.stdout.write(f'  - Backup: {"✓" if api_key.can_backup else "✗"}')
            self.stdout.write(f'  - Restore: {"✓" if api_key.can_restore else "✗"}')
            self.stdout.write(f'  - Ver logs: {"✓" if api_key.can_view_logs else "✗"}')
            self.stdout.write(f'  - Disparar migración: {"✓" if api_key.can_trigger_migration else "✗"}')
            
        except APIKey.DoesNotExist:
            raise CommandError(f'API key "{name}" no existe')
