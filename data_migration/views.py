from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from datetime import datetime
import logging

from .models import HiredEmployee, Department, Job, DataMigrationLog, SecurityLog
from .validators import validate_and_log_record, DataQualityLogger
from .authentication import (
    APIKeyAuthentication,
    CanIngestPermission,
    CanBackupPermission,
    CanRestorePermission,
    CanViewLogsPermission,
    CanTriggerMigrationPermission,
    RateLimitPermission
)
from .serializers import (
    HiredEmployeeSerializer, 
    DepartmentSerializer, 
    JobSerializer,
    BatchTransactionSerializer,
    MigrationLogSerializer
)
from .services import DataMigrationService
from django.conf import settings

from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONSerializer
from confluent_kafka import SerializingProducer
from confluent_kafka.serialization import StringSerializer

logger = logging.getLogger(__name__)
def _get_kafka_producer():
    schema_registry_conf = {"url": settings.SCHEMA_REGISTRY_URL}
    sr = SchemaRegistryClient(schema_registry_conf)

    # Simple schema with required title as per JSONSerializer requirements
    value_schema_str = (
        '{"title":"IngestEnvelope","type":"object","additionalProperties":false,'
        '"properties":{'
        '  "table":{"type":"string"},'
        '  "payload":{"type":"object"}'
        '},"required":["table","payload"]}'
    )
    json_serializer = JSONSerializer(value_schema_str, sr, to_dict=lambda v, ctx: v)

    producer_conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'key.serializer': StringSerializer('utf_8'),
        'value.serializer': json_serializer,
        'linger.ms': 10,
        'batch.num.messages': 1000
    }
    return SerializingProducer(producer_conf)

def _delivery_report(err, msg):
    if err is not None:
        logger.error(f"Kafka delivery failed: {err}")
    else:
        logger.info(f"Kafka delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")


@api_view(['POST'])
@permission_classes([CanIngestPermission, RateLimitPermission])
def ingest(request):
    """
    Ingest endpoint: accepts 1-1000 records with table routing.
    Validates minimal contract, logs rejected, publishes valid to Kafka 'raw' topic.
    """
    try:
        body = request.data
        table = body.get('table')
        records = body.get('records')

        if not isinstance(table, str) or table not in ['hired_employees', 'departments', 'jobs']:
            return Response({"error": "Invalid or missing table"}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(records, list) or not (1 <= len(records) <= 1000):
            return Response({"error": "records must be a list of 1..1000 items"}, status=status.HTTP_400_BAD_REQUEST)

        # Validación robusta usando el sistema de validadores
        valid = []
        errors = []
        
        for idx, r in enumerate(records):
            if not isinstance(r, dict):
                errors.append({"index": idx, "error": "record is not an object"})
                continue
            
            # Usar el validador robusto
            if validate_and_log_record(table, r, idx):
                valid.append(r)
            else:
                errors.append({"index": idx, "error": "record failed validation rules"})

        # log rejects; do not insert
        for e in errors:
            logger.warning(f"Rejected record: table={table} index={e['index']} reason={e['error']}")

        # produce valid to Kafka raw topic
        if not valid:
            # Nada válido: responde 400 con detalles
            return Response({
                "accepted": 0,
                "rejected": len(errors),
                "errors": errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Producir y confirmar entrega; si hay error, responder 500
        try:
            producer = _get_kafka_producer()
            raw_topic = f"raw.{table}"
            for r in valid:
                producer.produce(topic=raw_topic, key=str(r.get('id', '')), value={"table": table, "payload": r}, on_delivery=_delivery_report)
            producer.flush()
        except Exception as e:
            logger.error(f"Kafka produce error: {e}")
            return Response({
                "accepted": 0,
                "rejected": len(records),
                "errors": errors + [{"index": None, "error": f"kafka error: {str(e)}"}]
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "accepted": len(valid),
            "rejected": len(errors),
            "errors": errors
        }, status=status.HTTP_202_ACCEPTED)

    except Exception as e:
        logger.error(f"/ingest error: {e}")
        return Response({"error": "internal error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([CanBackupPermission, RateLimitPermission])
def backup_table(request, table: str):
    """Dispara un backup Parquet a MinIO para la tabla indicada. Chunk-size=1000 por defecto."""
    try:
        svc = DataMigrationService()
        uri = svc.backup_table_to_parquet_in_minio(table_name=table, chunk_size=1000)
        return Response({"message": "backup started/completed", "uri": uri}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def batch_transaction(request):
    """
    Endpoint para recibir lotes de transacciones (1-1000 registros)
    """
    serializer = BatchTransactionSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    table_name = serializer.validated_data['table_name']
    records = serializer.validated_data['records']
    
    migration_service = DataMigrationService()
    
    try:
        result = migration_service.process_batch(table_name, records)
        return Response({
            'message': f'Successfully processed {result["success_count"]} records',
            'success_count': result['success_count'],
            'error_count': result['error_count'],
            'errors': result['errors']
        }, status=status.HTTP_201_CREATED)
    
    except Exception as e:
        logger.error(f"Error processing batch for table {table_name}: {str(e)}")
        return Response({
            'error': 'Internal server error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([CanViewLogsPermission, RateLimitPermission])
def migration_logs(request):
    """
    Endpoint para consultar logs de migración
    """
    logs = DataMigrationLog.objects.all()[:100]  # Últimos 100 logs
    serializer = MigrationLogSerializer(logs, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])  # Health check siempre accesible
def health_check(request):
    """
    Health check endpoint
    """
    return Response({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'database': 'connected'
    })


@api_view(['POST'])
@permission_classes([CanTriggerMigrationPermission, RateLimitPermission])
def trigger_migration(request):
    """
    Endpoint para disparar la migración manualmente
    """
    try:
        migration_service = DataMigrationService()
        result = migration_service.run_full_migration()
        
        return Response({
            'message': 'Migration completed successfully',
            'result': result
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error running migration: {str(e)}")
        return Response({
            'error': 'Migration failed',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([CanRestorePermission, RateLimitPermission])
def restore_table(request, table):
    """
    Endpoint para restaurar una tabla desde backup Parquet en MinIO
    
    POST /api/restore/{table}/
    Body: {
        "backup_path": "backups/hired_employees/20251007T123456/",  # opcional, si no se especifica usa el último backup
        "chunk_size": 1000  # opcional, default 1000
    }
    """
    try:
        # Validar tabla
        valid_tables = ['hired_employees', 'departments', 'jobs']
        if table not in valid_tables:
            return Response({
                'error': 'Invalid table',
                'message': f'Table must be one of: {", ".join(valid_tables)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Obtener parámetros del request
        backup_path = request.data.get('backup_path')  # Opcional, si no se especifica usa el último
        
        chunk_size = request.data.get('chunk_size', 1000)
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            return Response({
                'error': 'Invalid chunk_size',
                'message': 'chunk_size must be a positive integer'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Ejecutar restauración
        migration_service = DataMigrationService()
        success = migration_service.restore_table_from_parquet_in_minio(
            table_name=table,
            backup_path=backup_path,
            chunk_size=chunk_size
        )
        
        if success:
            return Response({
                'message': f'Table {table} restored successfully',
                'backup_path': backup_path,
                'chunk_size': chunk_size
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': 'Restore failed',
                'message': f'Failed to restore table {table} from {backup_path}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    except Exception as e:
        logger.error(f"Error restoring table {table}: {e}")
        return Response({
            'error': 'Internal server error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([CanViewLogsPermission, RateLimitPermission])
def security_logs(request):
    """
    Endpoint para consultar logs de seguridad
    """
    try:
        # Obtener parámetros de filtrado
        event_type = request.GET.get('event_type')
        limit = int(request.GET.get('limit', 100))
        
        # Construir query
        queryset = SecurityLog.objects.all()
        
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        
        # Limitar resultados
        queryset = queryset[:limit]
        
        # Serializar datos
        logs_data = []
        for log in queryset:
            logs_data.append({
                'timestamp': log.timestamp.isoformat(),
                'event_type': log.event_type,
                'api_key_name': log.api_key_name,
                'ip_address': log.ip_address,
                'endpoint': log.endpoint,
                'method': log.method,
                'details': log.details
            })
        
        return Response({
            'logs': logs_data,
            'total': len(logs_data),
            'filters': {
                'event_type': event_type,
                'limit': limit
            }
        })
        
    except Exception as e:
        logger.error(f"Error retrieving security logs: {e}")
        return Response({
            'error': 'Internal server error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])  # Sin autenticación para PowerBI
def employees_by_quarter(request):
    """
    Métrica 1: Cantidad de empleados contratados por cargo y departamento, 
    divididos por trimestre. Optimizado para PowerBI.
    
    Parámetros:
    - year: Año a analizar (opcional, si no se especifica trae todos los años)
    """
    try:
        # Obtener año del parámetro (opcional)
        year_param = request.GET.get('year')
        
        if year_param:
            try:
                year = int(year_param)
                year_filter = "AND EXTRACT(YEAR FROM he.datetime) = %s"
                params = [year]
            except ValueError:
                return Response({
                    'error': 'Invalid year parameter',
                    'message': 'Year must be a valid integer'
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            year_filter = ""
            params = []
        
        # Consulta optimizada para PowerBI
        from django.db import connection
        
        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT 
                    EXTRACT(YEAR FROM he.datetime) as year,
                    d.name as department,
                    j.name as job,
                    SUM(CASE WHEN EXTRACT(QUARTER FROM he.datetime) = 1 THEN 1 ELSE 0 END) as q1,
                    SUM(CASE WHEN EXTRACT(QUARTER FROM he.datetime) = 2 THEN 1 ELSE 0 END) as q2,
                    SUM(CASE WHEN EXTRACT(QUARTER FROM he.datetime) = 3 THEN 1 ELSE 0 END) as q3,
                    SUM(CASE WHEN EXTRACT(QUARTER FROM he.datetime) = 4 THEN 1 ELSE 0 END) as q4
                FROM hired_employees he
                JOIN departments d ON he.department_id = d.id
                JOIN jobs j ON he.job_id = j.id
                WHERE 1=1 {year_filter}
                GROUP BY EXTRACT(YEAR FROM he.datetime), d.name, j.name
                ORDER BY EXTRACT(YEAR FROM he.datetime) DESC, d.name ASC, j.name ASC
            """, params)
            
            columns = [col[0] for col in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        return Response({
            'filtered_year': year_param,
            'data': results,
            'total_records': len(results)
        })
        
    except Exception as e:
        logger.error(f"Error generating employees by quarter metric: {e}")
        return Response({
            'error': 'Internal server error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])  # Sin autenticación para PowerBI
def departments_above_average(request):
    """
    Métrica 2: Departamentos que contratan más empleados que el promedio por año.
    Optimizado para PowerBI.
    
    Parámetros:
    - year: Año a analizar (opcional, si no se especifica trae todos los años)
    """
    try:
        # Obtener año del parámetro (opcional)
        year_param = request.GET.get('year')
        
        if year_param:
            try:
                year = int(year_param)
                year_filter = "AND EXTRACT(YEAR FROM he.datetime) = %s"
                params = [year]
            except ValueError:
                return Response({
                    'error': 'Invalid year parameter',
                    'message': 'Year must be a valid integer'
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            year_filter = ""
            params = []
        
        # Consulta optimizada para PowerBI
        from django.db import connection
        
        with connection.cursor() as cursor:
            # Calcular promedio y obtener departamentos arriba del promedio por año
            cursor.execute(f"""
                WITH yearly_stats AS (
                    SELECT 
                        EXTRACT(YEAR FROM he.datetime) as year,
                        d.id,
                        d.name as department,
                        COUNT(he.id) as hired
                    FROM departments d
                    LEFT JOIN hired_employees he ON d.id = he.department_id 
                        AND 1=1 {year_filter}
                    GROUP BY EXTRACT(YEAR FROM he.datetime), d.id, d.name
                ),
                yearly_averages AS (
                    SELECT 
                        year,
                        AVG(hired) as avg_hires
                    FROM yearly_stats
                    GROUP BY year
                )
                SELECT 
                    ys.year,
                    ys.id,
                    ys.department,
                    ys.hired,
                    ya.avg_hires
                FROM yearly_stats ys
                JOIN yearly_averages ya ON ys.year = ya.year
                WHERE ys.hired > ya.avg_hires
                ORDER BY ys.year DESC, ys.hired DESC
            """, params)
            
            columns = [col[0] for col in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        return Response({
            'filtered_year': year_param,
            'data': results,
            'total_records': len(results)
        })
        
    except Exception as e:
        logger.error(f"Error generating departments above average metric: {e}")
        return Response({
            'error': 'Internal server error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
