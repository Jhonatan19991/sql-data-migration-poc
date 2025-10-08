"""
Utilidades para el sistema de migración de datos
"""

import logging
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
import os

logger = logging.getLogger(__name__)


def validate_csv_structure(file_path: str, expected_columns: List[str]) -> bool:
    """
    Validar que un archivo CSV tenga la estructura esperada
    """
    try:
        # Leer las primeras líneas para detectar si tiene header
        with open(file_path, 'r') as f:
            first_line = f.readline().strip()
        
        # Si la primera línea parece ser un header (contiene texto), usarlo
        if any(col in first_line for col in expected_columns):
            df_header = pd.read_csv(file_path, nrows=0)
            actual_columns = list(df_header.columns)
            logger.info(f"CSV {file_path} has header: {actual_columns}")
        else:
            # Si no tiene header, usar las columnas esperadas
            actual_columns = expected_columns
            logger.info(f"CSV {file_path} has no header, using expected columns: {actual_columns}")
        
        # Verificar que todas las columnas esperadas estén presentes
        missing_columns = set(expected_columns) - set(actual_columns)
        if missing_columns:
            logger.error(f"Missing columns in {file_path}: {missing_columns}")
            logger.error(f"Expected: {expected_columns}, Found: {actual_columns}")
            return False
        
        # Verificar que no haya columnas extra
        extra_columns = set(actual_columns) - set(expected_columns)
        if extra_columns:
            logger.warning(f"Extra columns in {file_path}: {extra_columns}")
        
        logger.info(f"CSV structure validation passed for {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error validating CSV structure for {file_path}: {e}")
        return False


def get_csv_info(file_path: str) -> Dict[str, Any]:
    """
    Obtener información básica de un archivo CSV
    """
    try:
        # Leer solo las primeras filas para obtener información
        df_sample = pd.read_csv(file_path, nrows=1000)
        
        # Contar total de líneas (aproximado)
        with open(file_path, 'r') as f:
            total_lines = sum(1 for line in f) - 1  # -1 para el header
        
        return {
            'file_path': file_path,
            'total_rows': total_lines,
            'columns': list(df_sample.columns),
            'sample_data': df_sample.head(5).to_dict('records'),
            'file_size_mb': os.path.getsize(file_path) / (1024 * 1024)
        }
        
    except Exception as e:
        logger.error(f"Error getting CSV info for {file_path}: {e}")
        return {
            'file_path': file_path,
            'error': str(e)
        }


def clean_dataframe(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """
    Limpiar DataFrame según las reglas de cada tabla
    """
    try:
        # Eliminar filas completamente vacías
        df = df.dropna(how='all')
        
        if table_name == 'hired_employees':
            original_count = len(df)
            logger.info(f"Original records: {original_count}")
            
            # Eliminar filas con campos críticos vacíos o nulos
            df = df.dropna(subset=['id', 'name', 'datetime', 'department_id', 'job_id'])
            logger.info(f"After removing nulls: {len(df)} records")
            
            # Eliminar filas donde name esté vacío o sea solo espacios
            df = df[df['name'].astype(str).str.strip() != '']
            logger.info(f"After removing empty names: {len(df)} records")
            
            # Eliminar filas donde name sea 'nan' o 'None'
            df = df[~df['name'].astype(str).str.lower().isin(['nan', 'none', 'null'])]
            logger.info(f"After removing 'nan' names: {len(df)} records")
            
            # Limpiar nombres (remover espacios extra)
            df['name'] = df['name'].astype(str).str.strip()
            
            # Convertir datetime y eliminar filas con fechas inválidas
            df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
            df = df.dropna(subset=['datetime'])
            logger.info(f"After removing invalid dates: {len(df)} records")
            
            # Convertir department_id y job_id a enteros, eliminar filas con valores inválidos
            df['department_id'] = pd.to_numeric(df['department_id'], errors='coerce')
            df['job_id'] = pd.to_numeric(df['job_id'], errors='coerce')
            df = df.dropna(subset=['department_id', 'job_id'])
            logger.info(f"After removing invalid IDs: {len(df)} records")
            
            # Convertir a enteros
            df['department_id'] = df['department_id'].astype(int)
            df['job_id'] = df['job_id'].astype(int)
            
            # Eliminar filas con IDs negativos o cero
            df = df[(df['department_id'] > 0) & (df['job_id'] > 0)]
            logger.info(f"After removing invalid ID values: {len(df)} records")
            
            removed_count = original_count - len(df)
            logger.info(f"Removed {removed_count} invalid records ({removed_count/original_count*100:.1f}%)")
            
        elif table_name in ['departments', 'jobs']:
            # Eliminar filas con campos críticos vacíos
            df = df.dropna(subset=['id', 'name'])
            
            # Limpiar nombres
            df['name'] = df['name'].astype(str).str.strip()
        
        return df
        
    except Exception as e:
        logger.error(f"Error cleaning dataframe for {table_name}: {e}")
        return df


def create_backup_filename(table_name: str, format: str = 'parquet') -> str:
    """
    Crear nombre de archivo para backup
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"backup_{table_name}_{timestamp}.{format}"


def log_migration_error(table_name: str, record_id: str, error_type: str, 
                       error_message: str, raw_data: Dict = None):
    """
    Registrar error de migración en la base de datos
    """
    try:
        from .models import DataMigrationLog
        
        DataMigrationLog.objects.create(
            table_name=table_name,
            record_id=str(record_id),
            error_type=error_type,
            error_message=error_message,
            raw_data=raw_data
        )
        
    except Exception as e:
        logger.error(f"Error logging migration error: {e}")


def format_error_message(error: Exception, context: str = "") -> str:
    """
    Formatear mensaje de error para logging
    """
    error_type = type(error).__name__
    error_msg = str(error)
    
    if context:
        return f"[{context}] {error_type}: {error_msg}"
    else:
        return f"{error_type}: {error_msg}"
