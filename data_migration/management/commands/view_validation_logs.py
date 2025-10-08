"""
Comando para ver logs de validación de datos
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models
from datetime import timedelta
from data_migration.models import DataMigrationLog


class Command(BaseCommand):
    help = 'Ver logs de validación de datos'

    def add_arguments(self, parser):
        parser.add_argument(
            '--table',
            type=str,
            help='Filtrar por tabla específica (hired_employees, departments, jobs)'
        )
        parser.add_argument(
            '--error-type',
            type=str,
            help='Filtrar por tipo de error'
        )
        parser.add_argument(
            '--last-hours',
            type=int,
            default=24,
            help='Mostrar logs de las últimas N horas (default: 24)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Limitar número de resultados (default: 50)'
        )
        parser.add_argument(
            '--summary',
            action='store_true',
            help='Mostrar solo resumen estadístico'
        )

    def handle(self, *args, **options):
        table = options['table']
        error_type = options['error_type']
        last_hours = options['last_hours']
        limit = options['limit']
        summary = options['summary']
        
        # Calcular fecha de inicio
        start_time = timezone.now() - timedelta(hours=last_hours)
        
        # Construir query
        queryset = DataMigrationLog.objects.filter(timestamp__gte=start_time)
        
        if table:
            queryset = queryset.filter(table_name=table)
        
        if error_type:
            queryset = queryset.filter(error_type=error_type)
        
        if summary:
            self.show_summary(queryset)
        else:
            self.show_logs(queryset, limit)

    def show_summary(self, queryset):
        """Muestra resumen estadístico"""
        total_logs = queryset.count()
        
        if total_logs == 0:
            self.stdout.write(self.style.WARNING('No hay logs de validación en el período especificado'))
            return
        
        # Resumen por tabla
        self.stdout.write(self.style.SUCCESS('📊 Resumen de Logs de Validación'))
        self.stdout.write('=' * 50)
        
        tables = queryset.values_list('table_name', flat=True).distinct()
        for table in tables:
            table_logs = queryset.filter(table_name=table).count()
            self.stdout.write(f'{table}: {table_logs} logs')
        
        # Resumen por tipo de error
        self.stdout.write('\n📋 Resumen por Tipo de Error:')
        error_types = queryset.values('error_type').annotate(
            count=models.Count('id')
        ).order_by('-count')
        
        for error in error_types:
            self.stdout.write(f'  {error["error_type"]}: {error["count"]} ocurrencias')
        
        # Últimos errores
        self.stdout.write('\n🚨 Últimos 5 Errores:')
        recent_errors = queryset.order_by('-timestamp')[:5]
        for log in recent_errors:
            self.stdout.write(f'  {log.timestamp.strftime("%Y-%m-%d %H:%M:%S")} - {log.table_name} - {log.error_type}')

    def show_logs(self, queryset, limit):
        """Muestra logs detallados"""
        logs = queryset.order_by('-timestamp')[:limit]
        
        if not logs:
            self.stdout.write(self.style.WARNING('No hay logs de validación en el período especificado'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'📋 Últimos {len(logs)} Logs de Validación'))
        self.stdout.write('=' * 80)
        
        for log in logs:
            # Color según tipo de error
            if log.error_type == 'VALIDATION_ERROR':
                color = 'ERROR'
            elif log.error_type == 'MISSING_REQUIRED_FIELDS':
                color = 'WARNING'
            elif log.error_type == 'BATCH_SUMMARY':
                color = 'SUCCESS'
            else:
                color = 'WARNING'
            
            self.stdout.write(getattr(self.style, color)(
                f'[{log.timestamp.strftime("%Y-%m-%d %H:%M:%S")}] {log.table_name} - {log.error_type}'
            ))
            
            if log.record_id:
                self.stdout.write(f'  Record ID: {log.record_id}')
            
            self.stdout.write(f'  Error: {log.error_message}')
            
            if log.raw_data:
                self.stdout.write(f'  Data: {str(log.raw_data)[:100]}...')
            
            self.stdout.write('-' * 80)
