"""
Comando de Django para restaurar una tabla desde backup Parquet en MinIO
"""

from django.core.management.base import BaseCommand, CommandError
from data_migration.services import DataMigrationService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Restaura una tabla desde backup Parquet almacenado en MinIO'

    def add_arguments(self, parser):
        parser.add_argument(
            'table_name',
            type=str,
            help='Nombre de la tabla a restaurar (hired_employees, departments, jobs)'
        )
        parser.add_argument(
            'backup_path',
            type=str,
            nargs='?',  # Hacer opcional
            help='Ruta del backup en MinIO (ej: "backups/hired_employees/20251007T123456/"). Si no se especifica, usa el último backup disponible.'
        )
        parser.add_argument(
            '--chunk-size',
            type=int,
            default=1000,
            help='Tamaño de chunk para procesamiento (default: 1000)'
        )

    def handle(self, *args, **options):
        table_name = options['table_name']
        backup_path = options['backup_path']  # Puede ser None
        chunk_size = options['chunk_size']

        # Validar tabla
        valid_tables = ['hired_employees', 'departments', 'jobs']
        if table_name not in valid_tables:
            raise CommandError(f'Tabla inválida: {table_name}. Tablas válidas: {", ".join(valid_tables)}')

        if backup_path:
            self.stdout.write(
                self.style.SUCCESS(f'Iniciando restauración de {table_name} desde {backup_path}')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Iniciando restauración de {table_name} desde el último backup disponible')
            )

        try:
            # Crear servicio de migración
            migration_service = DataMigrationService()
            
            # Ejecutar restauración
            success = migration_service.restore_table_from_parquet_in_minio(
                table_name=table_name,
                backup_path=backup_path,
                chunk_size=chunk_size
            )

            if success:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Restauración exitosa de {table_name}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'✗ Error en la restauración de {table_name}')
                )
                raise CommandError('La restauración falló')

        except Exception as e:
            logger.error(f"Error en comando de restauración: {e}")
            self.stdout.write(
                self.style.ERROR(f'✗ Error durante la restauración: {e}')
            )
            raise CommandError(f'Error durante la restauración: {e}')
