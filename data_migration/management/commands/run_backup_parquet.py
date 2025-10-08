from django.core.management.base import BaseCommand
from data_migration.services import DataMigrationService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create Parquet backup for a table and upload to MinIO'

    def add_arguments(self, parser):
        parser.add_argument('table', type=str, help='Table name to backup')
        parser.add_argument('--chunk-size', type=int, default=100000)

    def handle(self, *args, **options):
        table = options['table']
        chunk_size = options['chunk_size']
        svc = DataMigrationService()
        try:
            uri = svc.backup_table_to_parquet_in_minio(table, chunk_size=chunk_size)
            self.stdout.write(self.style.SUCCESS(f'Backup completed: {uri}'))
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            self.stdout.write(self.style.ERROR(f'Backup failed: {str(e)}'))

