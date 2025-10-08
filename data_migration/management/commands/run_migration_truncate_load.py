from django.core.management.base import BaseCommand
from django.utils import timezone
import logging
import time
import os

from data_migration.services import DataMigrationService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run truncate load data migration from CSV files to MinIO and then to PostgreSQL'

    def add_arguments(self, parser):
        parser.add_argument(
            '--wait-for-minio',
            type=int,
            default=30,
            help='Wait time in seconds for MinIO to be ready'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Starting TRUNCATE LOAD data migration process...')
        )
        
        # Esperar a que MinIO esté listo
        wait_time = options['wait_for_minio']
        self.stdout.write(f'Waiting {wait_time} seconds for MinIO to be ready...')
        time.sleep(wait_time)
        
        try:
            migration_service = DataMigrationService()
            
            # Ejecutar migración con TRUNCATE previo paso a paso
            self.stdout.write('Running truncate load step-by-step migration...')
            
            # Paso 1: Departamentos
            self.stdout.write('Step 1: Migrating departments (truncate load)...')
            dept_success = self._migrate_table_truncate_load(migration_service, 'departments')
            if not dept_success:
                self.stdout.write(self.style.ERROR('Departments migration failed'))
                return
            
            # Paso 2: Trabajos
            self.stdout.write('Step 2: Migrating jobs (truncate load)...')
            job_success = self._migrate_table_truncate_load(migration_service, 'jobs')
            if not job_success:
                self.stdout.write(self.style.ERROR('Jobs migration failed'))
                return
            
            # Paso 3: Empleados
            self.stdout.write('Step 3: Migrating hired employees (truncate load)...')
            emp_success = self._migrate_table_truncate_load(migration_service, 'hired_employees')
            
            if not emp_success:
                self.stdout.write(self.style.ERROR('Employees migration failed'))
                return
            
            self.stdout.write(
                self.style.SUCCESS('TRUNCATE LOAD data migration process completed successfully!')
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error during truncate load migration: {str(e)}')
            )
            logger.error(f"Truncate load migration command error: {e}")
            raise
    
    def _migrate_table_truncate_load(self, migration_service, table_name):
        """Migrar una tabla específica usando método truncate load"""
        try:
            # Cargar CSV a MinIO
            csv_files = {
                'hired_employees': '/app/data/hired_employees.csv',
                'departments': '/app/data/departments.csv',
                'jobs': '/app/data/jobs.csv'
            }
            
            csv_path = csv_files[table_name]
            if not os.path.exists(csv_path):
                self.stdout.write(
                    self.style.WARNING(f'CSV file not found: {csv_path}')
                )
                return False
            
            # Cargar a MinIO
            success = migration_service.load_csv_to_minio(csv_path, table_name)
            if not success:
                self.stdout.write(
                    self.style.ERROR(f'Failed to upload {table_name} to MinIO')
                )
                return False
            
            # Cargar a PostgreSQL usando método truncate load
            success = migration_service.load_from_minio_to_postgres(table_name)
            if success:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ {table_name}: Successfully migrated (TRUNCATE LOAD)')
                )
                return True
            else:
                self.stdout.write(
                    self.style.ERROR(f'✗ {table_name}: Failed to load to PostgreSQL')
                )
                return False
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error migrating {table_name}: {str(e)}')
            )
            return False
