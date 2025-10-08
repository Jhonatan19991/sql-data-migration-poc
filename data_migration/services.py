"""
Servicio de migración con TRUNCATE para limpiar tablas completamente
"""

import os
import pandas as pd
import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.utils import timezone
from datetime import datetime
import logging
import io
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import IntegrityError
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .models import HiredEmployee, Department, Job, DataMigrationLog
from .utils import validate_csv_structure, get_csv_info, clean_dataframe, log_migration_error

logger = logging.getLogger(__name__)


class MinIOService:
    """Servicio para interactuar con MinIO"""
    
    def __init__(self):
        self.client = boto3.client(
            's3',
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name='us-east-1'
        )
        self.bucket_name = settings.MINIO_BUCKET_NAME
    
    def upload_csv_to_minio(self, file_path, object_key):
        """Subir archivo CSV a MinIO"""
        try:
            self.client.upload_file(file_path, self.bucket_name, object_key)
            logger.info(f"Successfully uploaded {file_path} to MinIO as {object_key}")
            return True
        except ClientError as e:
            logger.error(f"Error uploading to MinIO: {e}")
            return False


class DataMigrationService:
    """Servicio de migración con TRUNCATE para limpiar tablas"""
    
    def __init__(self):
        self.minio_service = MinIOService()
        self.bucket_name = settings.MINIO_BUCKET_NAME
        self.batch_size = 1000  # Requisito específico: 1000 registros por lote
    
    def load_csv_to_minio(self, csv_path, table_name):
        """Cargar CSV completo a MinIO como archivo CSV"""
        try:
            # Validar estructura del CSV
            expected_columns = self._get_expected_columns(table_name)
            if not validate_csv_structure(csv_path, expected_columns):
                logger.error(f"CSV structure validation failed for {csv_path}")
                return False
            
            # Obtener información del CSV
            csv_info = get_csv_info(csv_path)
            logger.info(f"Processing CSV: {csv_info}")
            
            # Crear nombre del archivo en MinIO
            object_key = f"raw_data/{table_name}/{table_name}.csv"
            
            # Subir archivo CSV completo a MinIO
            success = self.minio_service.upload_csv_to_minio(csv_path, object_key)
            
            if success:
                logger.info(f"Successfully uploaded {csv_path} to MinIO as {object_key}")
                return True
            else:
                logger.error(f"Failed to upload {csv_path} to MinIO")
                return False
            
        except Exception as e:
            logger.error(f"Error loading CSV {csv_path}: {e}")
            return False
    
    def load_from_minio_to_postgres(self, table_name):
        """Cargar datos de MinIO a PostgreSQL con TRUNCATE previo"""
        try:
            # Limpiar tabla con TRUNCATE antes de cargar
            self._truncate_table_before_load(table_name)
            
            # Obtener columnas esperadas para esta tabla
            expected_columns = self._get_expected_columns(table_name)
            
            # Listar archivos en MinIO
            response = self.minio_service.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f"raw_data/{table_name}/"
            )
            
            for obj in response.get('Contents', []):
                if obj['Key'].endswith('.csv'):
                    logger.info(f"Processing file: {obj['Key']}")
                    
                    # Leer archivo desde MinIO
                    try:
                        response = self.minio_service.client.get_object(
                            Bucket=self.bucket_name,
                            Key=obj['Key']
                        )
                        
                        # Leer contenido del archivo
                        content = response['Body'].read().decode('utf-8')
                        
                        # Procesar con limpieza robusta
                        self._process_csv(content, table_name, expected_columns)
                        
                    except Exception as e:
                        logger.error(f"Error processing file {obj['Key']}: {e}")
                        continue
            
            logger.info(f"Successfully loaded {table_name} from MinIO to PostgreSQL")
            return True
            
        except Exception as e:
            logger.error(f"Error loading {table_name} from MinIO to PostgreSQL: {e}")
            return False
    
    def _truncate_table_before_load(self, table_name):
        """Limpiar tabla con TRUNCATE antes de cargar datos"""
        try:
            conn = psycopg2.connect(
                host=settings.DATABASES['default']['HOST'],
                port=settings.DATABASES['default']['PORT'],
                database=settings.DATABASES['default']['NAME'],
                user=settings.DATABASES['default']['USER'],
                password=settings.DATABASES['default']['PASSWORD']
            )
            
            try:
                with conn.cursor() as cursor:
                    # Usar TRUNCATE para limpiar completamente la tabla
                    cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE")
                    logger.info(f"Truncated table {table_name} with RESTART IDENTITY")
                    
                    conn.commit()
                    
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"Error truncating table {table_name}: {e}")
            # No lanzar excepción, continuar con la carga
    
    def _process_csv(self, content, table_name, expected_columns):
        """Procesar CSV con limpieza robusta"""
        try:
            lines = content.split('\n')
            
            if not lines or not lines[0].strip():
                return
            
            # Detectar si tiene header
            first_line = lines[0].strip()
            has_header = any(col in first_line for col in expected_columns)
            
            if has_header:
                # Leer con header
                df = pd.read_csv(
                    io.StringIO(content),
                    na_filter=False,  # No crear NaN automáticamente
                    engine='c'
                )
                logger.info(f"Reading CSV with header: {list(df.columns)}")
            else:
                # Leer sin header, usar nombres de columnas esperadas
                df = pd.read_csv(
                    io.StringIO(content),
                    names=expected_columns,
                    header=None,
                    na_filter=False,
                    engine='c'
                )
                logger.info(f"Reading CSV without header, using: {expected_columns}")
            
            # Limpiar datos con manejo robusto
            df = self._clean_dataframe(df, table_name)
            logger.info(f"Cleaned dataframe shape: {df.shape}")
            
            if df.empty:
                logger.warning("DataFrame is empty after cleaning")
                return
            
            # Cargar en lotes de 1000 usando COPY de PostgreSQL
            self._load_with_copy_batches(df, table_name)
            
        except Exception as e:
            logger.error(f"Error processing CSV: {e}")
            raise
    
    def _clean_dataframe(self, df, table_name):
        """Limpieza robusta de DataFrame"""
        try:
            original_count = len(df)
            logger.info(f"Original records: {original_count}")
            
            if table_name == 'hired_employees':
                # Paso 1: Eliminar filas completamente vacías
                df = df.dropna(how='all')
                
                # Paso 2: Reemplazar valores problemáticos con NaN
                df = df.replace(['nan', 'NaN', 'NAN', 'null', 'NULL', 'None', 'NONE', ''], pd.NA)
                
                # Paso 3: Eliminar filas con campos críticos nulos
                df = df.dropna(subset=['id', 'name', 'datetime', 'department_id', 'job_id'])
                logger.info(f"After removing nulls in critical fields: {len(df)} records")
                
                # Paso 4: Limpiar nombres
                df['name'] = df['name'].astype(str).str.strip()
                df = df[df['name'] != '']
                df = df[~df['name'].str.lower().isin(['nan', 'none', 'null', ''])]
                logger.info(f"After cleaning names: {len(df)} records")
                
                # Paso 5: Convertir datetime con manejo robusto
                df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
                df = df.dropna(subset=['datetime'])
                logger.info(f"After cleaning dates: {len(df)} records")
                
                # Paso 6: Convertir IDs con manejo robusto
                df['department_id'] = df['department_id'].astype(str).str.strip()
                df['job_id'] = df['job_id'].astype(str).str.strip()
                
                # Eliminar valores problemáticos
                df = df[~df['department_id'].isin(['nan', 'NaN', 'NAN', 'null', 'NULL', 'None', 'NONE', ''])]
                df = df[~df['job_id'].isin(['nan', 'NaN', 'NAN', 'null', 'NULL', 'None', 'NONE', ''])]
                
                # Convertir a numérico con manejo de errores
                df['department_id'] = pd.to_numeric(df['department_id'], errors='coerce')
                df['job_id'] = pd.to_numeric(df['job_id'], errors='coerce')
                
                # Eliminar filas con valores no numéricos
                df = df.dropna(subset=['department_id', 'job_id'])
                logger.info(f"After converting to numeric: {len(df)} records")
                
                # Convertir a enteros
                if not df.empty:
                    df['department_id'] = df['department_id'].astype('int32')
                    df['job_id'] = df['job_id'].astype('int32')
                    
                    # Eliminar filas con IDs negativos o cero
                    df = df[(df['department_id'] > 0) & (df['job_id'] > 0)]
                    logger.info(f"After removing invalid ID values: {len(df)} records")
                
                # Eliminar duplicados por ID (más robusto)
                original_count = len(df)
                df = df.drop_duplicates(subset=['id'], keep='first')
                duplicates_removed = original_count - len(df)
                if duplicates_removed > 0:
                    logger.info(f"Removed {duplicates_removed} duplicate records by ID")
                
                # Verificar que no hay duplicados restantes
                remaining_duplicates = df.duplicated(subset=['id']).sum()
                if remaining_duplicates > 0:
                    logger.warning(f"Still {remaining_duplicates} duplicate IDs found, removing them")
                    df = df.drop_duplicates(subset=['id'], keep='first')
                    logger.info(f"Final duplicate removal: {remaining_duplicates} records")
                
            elif table_name in ['departments', 'jobs']:
                # Limpieza para departamentos y trabajos
                df = df.dropna(how='all')
                df = df.replace(['nan', 'NaN', 'NAN', 'null', 'NULL', 'None', 'NONE', ''], pd.NA)
                df = df.dropna(subset=['id', 'name'])
                
                # Limpiar nombres
                df['name'] = df['name'].astype(str).str.strip()
                df = df[df['name'] != '']
                
                # Convertir ID a entero
                if not df.empty:
                    df['id'] = df['id'].astype('int32')
                
                # Eliminar duplicados por ID
                original_count = len(df)
                df = df.drop_duplicates(subset=['id'], keep='first')
                duplicates_removed = original_count - len(df)
                if duplicates_removed > 0:
                    logger.info(f"Removed {duplicates_removed} duplicate records by ID")
            
            removed_count = original_count - len(df)
            logger.info(f"Removed {removed_count} invalid records ({removed_count/original_count*100:.1f}%)")
            
            return df
            
        except Exception as e:
            logger.error(f"Error cleaning dataframe: {e}")
            return df
    
    
    def _load_with_copy_batches(self, df, table_name):
        """Cargar datos en lotes de 1000 usando COPY de PostgreSQL"""
        try:
            total_rows = len(df)
            logger.info(f"Loading {total_rows} rows in batches of {self.batch_size}")
            
            for i in range(0, total_rows, self.batch_size):
                batch_df = df.iloc[i:i + self.batch_size]
                batch_num = (i // self.batch_size) + 1
                total_batches = (total_rows + self.batch_size - 1) // self.batch_size
                
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_df)} rows)")
                
                # Cargar lote usando COPY
                self._load_with_copy(batch_df, table_name)
                
                logger.info(f"Completed batch {batch_num}/{total_batches}")
                
        except Exception as e:
            logger.error(f"Error loading {table_name} in batches: {e}")
            raise
    
    def _load_with_copy(self, df, table_name):
        """Cargar datos usando COPY de PostgreSQL"""
        try:
            # Obtener conexión a PostgreSQL
            conn = psycopg2.connect(
                host=settings.DATABASES['default']['HOST'],
                port=settings.DATABASES['default']['PORT'],
                database=settings.DATABASES['default']['NAME'],
                user=settings.DATABASES['default']['USER'],
                password=settings.DATABASES['default']['PASSWORD']
            )
            
            try:
                with conn.cursor() as cursor:
                    # Preparar datos para COPY
                    if table_name == 'hired_employees':
                        self._copy_hired_employees(cursor, df)
                    elif table_name == 'departments':
                        self._copy_departments(cursor, df)
                    elif table_name == 'jobs':
                        self._copy_jobs(cursor, df)
                    
                    conn.commit()
                    logger.info(f"Successfully loaded {len(df)} records to {table_name}")
                    
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"Error loading with COPY: {e}")
            raise
    
    def _load_with_copy_no_id(self, df, table_name):
        """Cargar datos usando COPY dejando que Postgres autoincremente id (solo hired_employees)."""
        try:
            conn = psycopg2.connect(
                host=settings.DATABASES['default']['HOST'],
                port=settings.DATABASES['default']['PORT'],
                database=settings.DATABASES['default']['NAME'],
                user=settings.DATABASES['default']['USER'],
                password=settings.DATABASES['default']['PASSWORD']
            )
            try:
                with conn.cursor() as cursor:
                    # Asegurar que la columna id tenga identidad autogenerada
                    try:
                        cursor.execute(
                            "ALTER TABLE hired_employees ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY"
                        )
                        logger.info("Enabled IDENTITY on hired_employees.id")
                        conn.commit()
                    except Exception:
                        # Ya estaba configurado o no soportado; continuar
                        conn.rollback()
                    if table_name == 'hired_employees':
                        self._copy_hired_employees_no_id(cursor, df)
                    else:
                        # Para otras tablas no aplicamos no-id; usar método normal
                        self._copy_departments_truncate_load(cursor, df) if table_name == 'departments' else None
                    conn.commit()
                    logger.info(f"Successfully loaded {len(df)} records to {table_name} (no id)")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Error loading with COPY (no id): {e}")
            raise

    def _copy_hired_employees(self, cursor, df):
        """Cargar empleados usando COPY"""
        # Crear copia para no modificar el original
        df_copy = df.copy()
        
        # Convertir datetime a string para COPY
        df_copy['datetime'] = df_copy['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Asegurar que todos los valores sean strings válidos
        df_copy['id'] = df_copy['id'].astype(str)
        df_copy['name'] = df_copy['name'].astype(str)
        df_copy['department_id'] = df_copy['department_id'].astype(str)
        df_copy['job_id'] = df_copy['job_id'].astype(str)
        
        # Crear StringIO para COPY
        output = io.StringIO()
        df_copy.to_csv(output, sep='\t', header=False, index=False, na_rep='\\N')
        output.seek(0)
        
        # Ejecutar COPY
        cursor.copy_from(
            output,
            'hired_employees',
            columns=('id', 'name', 'datetime', 'department_id', 'job_id'),
            sep='\t',
            null='\\N'
        )

    def _copy_hired_employees_no_id(self, cursor, df):
        """Cargar empleados usando COPY dejando que Postgres autoincremente id"""
        df_copy = df.copy()
        # Convertir datetime a string para COPY
        df_copy['datetime'] = pd.to_datetime(df_copy['datetime'], errors='coerce')
        df_copy = df_copy.dropna(subset=['datetime'])
        df_copy['datetime'] = df_copy['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df_copy['name'] = df_copy['name'].astype(str)
        df_copy['department_id'] = pd.to_numeric(df_copy['department_id'], errors='coerce')
        df_copy['job_id'] = pd.to_numeric(df_copy['job_id'], errors='coerce')
        df_copy = df_copy.dropna(subset=['department_id','job_id'])
        df_copy[['department_id','job_id']] = df_copy[['department_id','job_id']].astype('int64')

        output = io.StringIO()
        # Importante: no incluir la columna id para que Postgres use la secuencia
        df_copy[['name','datetime','department_id','job_id']].to_csv(output, sep='\t', header=False, index=False, na_rep='\\N')
        output.seek(0)
        cursor.copy_from(
            output,
            'hired_employees',
            columns=('name', 'datetime', 'department_id', 'job_id'),
            sep='\t',
            null='\\N'
        )
    
    def _copy_departments(self, cursor, df):
        """Cargar departamentos usando COPY"""
        df_copy = df.copy()
        df_copy['id'] = df_copy['id'].astype(str)
        df_copy['name'] = df_copy['name'].astype(str)
        
        output = io.StringIO()
        df_copy.to_csv(output, sep='\t', header=False, index=False, na_rep='\\N')
        output.seek(0)
        
        cursor.copy_from(
            output,
            'departments',
            columns=('id', 'name'),
            sep='\t',
            null='\\N'
        )
    
    def _copy_jobs(self, cursor, df):
        """Cargar trabajos usando COPY"""
        df_copy = df.copy()
        df_copy['id'] = df_copy['id'].astype(str)
        df_copy['name'] = df_copy['name'].astype(str)
        
        output = io.StringIO()
        df_copy.to_csv(output, sep='\t', header=False, index=False, na_rep='\\N')
        output.seek(0)
        
        cursor.copy_from(
            output,
            'jobs',
            columns=('id', 'name'),
            sep='\t',
            null='\\N'
        )
    
    def _get_expected_columns(self, table_name):
        """Obtener columnas esperadas para cada tabla"""
        column_mapping = {
            'hired_employees': ['id', 'name', 'datetime', 'department_id', 'job_id'],
            'departments': ['id', 'name'],
            'jobs': ['id', 'name']
        }
        return column_mapping.get(table_name, [])
    
    def run_full_migration(self):
        """Ejecutar migración completa con TRUNCATE previo"""
        try:
            # Rutas de los archivos CSV
            csv_files = {
                'hired_employees': '/app/data/hired_employees.csv',
                'departments': '/app/data/departments.csv',
                'jobs': '/app/data/jobs.csv'
            }
            
            results = {}
            
            for table_name, csv_path in csv_files.items():
                logger.info(f"Starting truncate load migration for {table_name}")
                
                # 1. Cargar CSV completo a MinIO
                if os.path.exists(csv_path):
                    success = self.load_csv_to_minio(csv_path, table_name)
                    if success:
                        # 2. Cargar de MinIO a PostgreSQL con TRUNCATE previo
                        success = self.load_from_minio_to_postgres(table_name)
                        results[table_name] = 'success' if success else 'failed'
                    else:
                        results[table_name] = 'failed'
                else:
                    logger.warning(f"CSV file not found: {csv_path}")
                    results[table_name] = 'file_not_found'
            
            return results
            
        except Exception as e:
            logger.error(f"Error in truncate load migration: {e}")
            return {'error': str(e)}

    def backup_table_to_parquet_in_minio(self, table_name: str, chunk_size: int = 1000) -> str:
        """Genera backup Parquet de una tabla y lo sube a MinIO. Devuelve el object key.

        - Exporta en chunks para bajo uso de memoria
        - Parquet con compresión snappy
        - Ruta en MinIO: backups/{table}/{ts}/part-XXXX.parquet
        """
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
        object_prefix = f"backups/{table_name}/{ts}"
        tmp_files = []
        try:
            conn = psycopg2.connect(
                host=settings.DATABASES['default']['HOST'],
                port=settings.DATABASES['default']['PORT'],
                database=settings.DATABASES['default']['NAME'],
                user=settings.DATABASES['default']['USER'],
                password=settings.DATABASES['default']['PASSWORD']
            )
            try:
                with conn.cursor(name=f"cur_{table_name}_{ts}") as cursor:
                    cursor.itersize = 10000
                    cursor.execute(f'SELECT * FROM "{table_name}"')
                    part = 0
                    while True:
                        rows = cursor.fetchmany(chunk_size)
                        if not rows:
                            break
                        colnames = [desc[0] for desc in cursor.description]
                        batch_df = pd.DataFrame(rows, columns=colnames)
                        table = pa.Table.from_pandas(batch_df, preserve_index=False)
                        tmp_path = f"/tmp/{table_name}_{ts}_part{part}.parquet"
                        pq.write_table(table, tmp_path, compression='snappy')
                        tmp_files.append((tmp_path, f"{object_prefix}/part-{part:04d}.parquet"))
                        part += 1
            finally:
                conn.close()

            # Subir a MinIO
            client = boto3.client(
                's3',
                endpoint_url=settings.MINIO_ENDPOINT,
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
                region_name='us-east-1'
            )
            bucket = settings.MINIO_BUCKET_NAME
            for local_path, obj_key in tmp_files:
                client.upload_file(local_path, bucket, obj_key)
                logger.info(f"Uploaded backup part to MinIO: s3://{bucket}/{obj_key}")

            return f"s3://{bucket}/{object_prefix}/"
        except Exception as e:
            logger.error(f"Backup to Parquet failed for {table_name}: {e}")
            raise
        finally:
            for local_path, _ in tmp_files:
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                except Exception:
                    pass

    def get_latest_backup_path(self, table_name: str) -> str:
        """Obtiene la ruta del último backup para una tabla específica.
        
        Args:
            table_name: Nombre de la tabla
            
        Returns:
            str: Ruta del último backup o None si no se encuentra
        """
        try:
            client = boto3.client(
                's3',
                endpoint_url=settings.MINIO_ENDPOINT,
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
                region_name='us-east-1'
            )
            bucket = settings.MINIO_BUCKET_NAME
            
            # Listar backups para la tabla
            prefix = f"backups/{table_name}/"
            response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter='/')
            
            if 'CommonPrefixes' not in response:
                logger.warning(f"No backups found for table {table_name}")
                return None
            
            # Obtener todos los timestamps de backup
            backup_timestamps = []
            for prefix_info in response['CommonPrefixes']:
                # Extraer timestamp del path: backups/table_name/20251007T123456/
                path = prefix_info['Prefix']
                timestamp_part = path.split('/')[-2]  # Obtener la parte del timestamp
                if timestamp_part and len(timestamp_part) == 15:  # Formato: 20251007T123456
                    backup_timestamps.append(timestamp_part)
            
            if not backup_timestamps:
                logger.warning(f"No valid backup timestamps found for table {table_name}")
                return None
            
            # Ordenar y obtener el más reciente
            latest_timestamp = sorted(backup_timestamps, reverse=True)[0]
            latest_backup_path = f"backups/{table_name}/{latest_timestamp}/"
            
            logger.info(f"Latest backup for {table_name}: {latest_backup_path}")
            return latest_backup_path
            
        except Exception as e:
            logger.error(f"Error getting latest backup for {table_name}: {e}")
            return None

    def restore_table_from_parquet_in_minio(self, table_name: str, backup_path: str = None, chunk_size: int = 1000) -> bool:
        """Restaura una tabla desde backup Parquet en MinIO.

        Args:
            table_name: Nombre de la tabla a restaurar
            backup_path: Ruta del backup en MinIO (ej: "backups/hired_employees/20251007T123456/")
            chunk_size: Tamaño de chunk para procesamiento (default: 1000)

        Returns:
            bool: True si la restauración fue exitosa, False en caso contrario
        """
        try:
            # Si no se especifica backup_path, usar el último backup
            if backup_path is None:
                backup_path = self.get_latest_backup_path(table_name)
                if backup_path is None:
                    logger.error(f"No backups found for table {table_name}")
                    return False
                logger.info(f"Using latest backup: {backup_path}")
            
            # Limpiar la tabla antes de restaurar
            logger.info(f"Clearing table {table_name} before restore")
            self._truncate_table_before_load(table_name)
            
            # Configurar cliente MinIO
            client = boto3.client(
                's3',
                endpoint_url=settings.MINIO_ENDPOINT,
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
                region_name='us-east-1'
            )
            bucket = settings.MINIO_BUCKET_NAME
            
            # Listar archivos Parquet en el backup
            if backup_path.startswith('s3://'):
                # Extraer bucket y prefix de la URL s3://
                parts = backup_path[5:].split('/', 1)
                if len(parts) == 2:
                    bucket, prefix = parts
                else:
                    prefix = parts[0]
            else:
                prefix = backup_path.rstrip('/')
            
            # Listar objetos en el prefijo
            response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
            parquet_files = []
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    if obj['Key'].endswith('.parquet'):
                        parquet_files.append(obj['Key'])
            
            if not parquet_files:
                logger.error(f"No Parquet files found in backup path: {backup_path}")
                return False
            
            logger.info(f"Found {len(parquet_files)} Parquet files to restore")
            
            # Procesar cada archivo Parquet
            total_restored = 0
            for parquet_file in sorted(parquet_files):
                logger.info(f"Processing backup file: {parquet_file}")
                
                # Descargar archivo Parquet temporalmente
                tmp_path = f"/tmp/restore_{table_name}_{os.path.basename(parquet_file)}"
                client.download_file(bucket, parquet_file, tmp_path)
                
                try:
                    # Leer Parquet con PyArrow
                    table = pq.read_table(tmp_path)
                    df = table.to_pandas()
                    
                    if df.empty:
                        logger.warning(f"Empty Parquet file: {parquet_file}")
                        continue
                    
                    logger.info(f"Loaded {len(df)} records from {parquet_file}")
                    
                    # Restaurar en lotes
                    restored_count = self._restore_dataframe_to_postgres(df, table_name, chunk_size)
                    total_restored += restored_count
                    
                    logger.info(f"Restored {restored_count} records from {parquet_file}")
                    
                finally:
                    # Limpiar archivo temporal
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            
            logger.info(f"Successfully restored {total_restored} records to {table_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error restoring {table_name} from backup {backup_path}: {e}")
            return False

    def _restore_dataframe_to_postgres(self, df: pd.DataFrame, table_name: str, chunk_size: int) -> int:
        """Restaura un DataFrame a PostgreSQL en lotes usando COPY.
        
        Args:
            df: DataFrame a restaurar
            table_name: Nombre de la tabla
            chunk_size: Tamaño de lote
            
        Returns:
            int: Número de registros restaurados
        """
        try:
            conn = psycopg2.connect(
                host=settings.DATABASES['default']['HOST'],
                port=settings.DATABASES['default']['PORT'],
                database=settings.DATABASES['default']['NAME'],
                user=settings.DATABASES['default']['USER'],
                password=settings.DATABASES['default']['PASSWORD']
            )
            
            try:
                with conn.cursor() as cursor:
                    total_restored = 0
                    
                    # Procesar en lotes
                    for i in range(0, len(df), chunk_size):
                        batch_df = df.iloc[i:i + chunk_size].copy()
                        
                        if batch_df.empty:
                            continue
                        
                        # Preparar datos para COPY
                        batch_df = batch_df.replace({np.nan: None})
                        
                        # Crear buffer de datos
                        buffer = io.StringIO()
                        batch_df.to_csv(buffer, sep='\t', na_rep='\\N', header=False, index=False)
                        buffer.seek(0)
                        
                        # Ejecutar COPY
                        if table_name == 'hired_employees':
                            # Para hired_employees, manejar id opcional
                            if 'id' in batch_df.columns and batch_df['id'].notna().any():
                                # Con ID
                                cursor.copy_from(
                                    buffer,
                                    table_name,
                                    columns=('id', 'name', 'datetime', 'department_id', 'job_id'),
                                    sep='\t',
                                    null='\\N'
                                )
                            else:
                                # Sin ID (autoincremental)
                                cursor.copy_from(
                                    buffer,
                                    table_name,
                                    columns=('name', 'datetime', 'department_id', 'job_id'),
                                    sep='\t',
                                    null='\\N'
                                )
                        else:
                            # Para departments y jobs
                            cursor.copy_from(
                                buffer,
                                table_name,
                                columns=tuple(batch_df.columns),
                                sep='\t',
                                null='\\N'
                            )
                        
                        total_restored += len(batch_df)
                        logger.info(f"Restored batch {i//chunk_size + 1}: {len(batch_df)} records")
                    
                    conn.commit()
                    return total_restored
                    
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"Error restoring DataFrame to PostgreSQL: {e}")
            raise