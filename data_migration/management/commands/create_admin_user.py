"""
Comando para crear un superusuario por defecto
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.core.management import call_command
import getpass
import sys


class Command(BaseCommand):
    help = 'Crea un superusuario para acceder al Django Admin'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='admin',
            help='Nombre de usuario del superusuario (default: admin)'
        )
        parser.add_argument(
            '--email',
            type=str,
            default='admin@example.com',
            help='Email del superusuario (default: admin@example.com)'
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Contraseña del superusuario (se pedirá si no se especifica)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar creación aunque ya exista un superusuario'
        )

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']
        force = options['force']
        
        # Verificar si ya existe un superusuario
        if User.objects.filter(is_superuser=True).exists() and not force:
            self.stdout.write(
                self.style.WARNING('⚠️  Ya existe un superusuario en el sistema.')
            )
            self.stdout.write('Usa --force para crear otro superusuario.')
            return
        
        # Obtener contraseña si no se proporcionó
        if not password:
            self.stdout.write(f'Creando superusuario: {username}')
            self.stdout.write(f'Email: {email}')
            
            while True:
                password = getpass.getpass('Contraseña: ')
                if len(password) < 8:
                    self.stdout.write(
                        self.style.ERROR('❌ La contraseña debe tener al menos 8 caracteres')
                    )
                    continue
                
                password_confirm = getpass.getpass('Confirmar contraseña: ')
                if password != password_confirm:
                    self.stdout.write(
                        self.style.ERROR('❌ Las contraseñas no coinciden')
                    )
                    continue
                break
        
        try:
            # Crear superusuario
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            
            self.stdout.write(
                self.style.SUCCESS(f'✅ Superusuario "{username}" creado exitosamente!')
            )
            self.stdout.write('')
            self.stdout.write('🔗 Accede al panel de administración en:')
            self.stdout.write('   http://localhost:8000/admin/')
            self.stdout.write('')
            self.stdout.write('📋 Credenciales:')
            self.stdout.write(f'   Usuario: {username}')
            self.stdout.write(f'   Email: {email}')
            self.stdout.write('   Contraseña: [la que ingresaste]')
            self.stdout.write('')
            self.stdout.write('🔑 Desde el admin podrás:')
            self.stdout.write('   • Crear y gestionar API Keys')
            self.stdout.write('   • Ver logs de seguridad')
            self.stdout.write('   • Monitorear rate limits')
            self.stdout.write('   • Ver logs de migración')
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error creando superusuario: {e}')
            )
            sys.exit(1)
