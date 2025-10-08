"""
Validadores de reglas de calidad de datos
"""

import re
import logging
import json
from datetime import datetime
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import DataMigrationLog, Department, Job, HiredEmployee
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def clean_data_for_json(data):
    """
    Limpia datos para serialización JSON, convirtiendo tipos no serializables
    
    Args:
        data: Datos a limpiar
        
    Returns:
        dict: Datos limpios y serializables
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            cleaned[key] = clean_data_for_json(value)
        return cleaned
    elif isinstance(data, list):
        return [clean_data_for_json(item) for item in data]
    elif isinstance(data, pd.Timestamp):
        return data.isoformat()
    elif isinstance(data, np.datetime64):
        return pd.Timestamp(data).isoformat()
    elif isinstance(data, np.integer):
        return int(data)
    elif isinstance(data, np.floating):
        return float(data) if not pd.isna(data) else None
    elif isinstance(data, np.bool_):
        return bool(data)
    elif pd.isna(data):
        return None
    elif isinstance(data, (int, float, str, bool)) or data is None:
        return data
    else:
        # Para cualquier otro tipo, convertir a string
        return str(data)


class DataQualityValidator:
    """Validador de reglas de calidad de datos"""
    
    @staticmethod
    def validate_hired_employee(record, record_id=None):
        """
        Valida un registro de hired_employee contra las reglas de calidad
        
        Args:
            record: Diccionario con los datos del registro
            record_id: ID del registro (opcional)
            
        Returns:
            tuple: (is_valid, error_message, error_type)
        """
        errors = []
        
        # Validar campos requeridos
        required_fields = ['name', 'datetime', 'department_id', 'job_id']
        for field in required_fields:
            if field not in record or not record[field] or str(record[field]).strip() == '':
                errors.append(f"Campo requerido '{field}' está vacío o faltante")
        
        if errors:
            return False, '; '.join(errors), 'MISSING_REQUIRED_FIELDS'
        
        # Validar nombre
        name = str(record['name']).strip()
        if len(name) < 2:
            errors.append("Nombre debe tener al menos 2 caracteres")
        elif len(name) > 255:
            errors.append("Nombre no puede exceder 255 caracteres")
        elif not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\.]+$', name):
            errors.append("Nombre contiene caracteres inválidos")
        
        # Validar datetime
        try:
            datetime_value = record['datetime']
            
            # Convertir a datetime si es necesario
            if isinstance(datetime_value, str):
                # Intentar parsear diferentes formatos
                dt = None
                for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']:
                    try:
                        dt = datetime.strptime(datetime_value, fmt)
                        break
                    except ValueError:
                        continue
                
                if dt is None:
                    errors.append("Formato de fecha inválido (esperado: YYYY-MM-DDTHH:MM:SS)")
                    return False, '; '.join(errors), 'VALIDATION_ERROR'
            elif isinstance(datetime_value, pd.Timestamp):
                # Convertir pandas Timestamp a datetime
                dt = datetime_value.to_pydatetime()
            elif isinstance(datetime_value, datetime):
                dt = datetime_value
            else:
                errors.append("Tipo de fecha inválido")
                return False, '; '.join(errors), 'VALIDATION_ERROR'
            
            # Hacer la fecha timezone-aware si no lo es
            if dt.tzinfo is None:
                dt = timezone.make_aware(dt)
            
            # Comparar con fecha actual
            if dt > timezone.now():
                errors.append("Fecha no puede ser futura")
                
        except Exception as e:
            errors.append(f"Error validando fecha: {str(e)}")
        
        # Validar department_id
        try:
            dept_id = int(record['department_id'])
            if dept_id <= 0:
                errors.append("department_id debe ser un entero positivo")
            elif not Department.objects.filter(id=dept_id).exists():
                errors.append(f"department_id {dept_id} no existe en la base de datos")
        except (ValueError, TypeError):
            errors.append("department_id debe ser un entero válido")
        
        # Validar job_id
        try:
            job_id = int(record['job_id'])
            if job_id <= 0:
                errors.append("job_id debe ser un entero positivo")
            elif not Job.objects.filter(id=job_id).exists():
                errors.append(f"job_id {job_id} no existe en la base de datos")
        except (ValueError, TypeError):
            errors.append("job_id debe ser un entero válido")
        
        # Validar id si está presente
        if 'id' in record and record['id'] is not None:
            try:
                emp_id = int(record['id'])
                if emp_id <= 0 or emp_id > 2147483647:
                    errors.append("id debe estar entre 1 y 2147483647")
                elif HiredEmployee.objects.filter(id=emp_id).exists():
                    errors.append(f"id {emp_id} ya existe en la base de datos")
            except (ValueError, TypeError):
                errors.append("id debe ser un entero válido")
        
        if errors:
            return False, '; '.join(errors), 'VALIDATION_ERROR'
        
        return True, None, None
    
    @staticmethod
    def validate_department(record, record_id=None):
        """
        Valida un registro de department
        
        Args:
            record: Diccionario con los datos del registro
            record_id: ID del registro (opcional)
            
        Returns:
            tuple: (is_valid, error_message, error_type)
        """
        errors = []
        
        # Validar campos requeridos
        if 'name' not in record or not record['name'] or str(record['name']).strip() == '':
            errors.append("Campo requerido 'name' está vacío o faltante")
        
        if errors:
            return False, '; '.join(errors), 'MISSING_REQUIRED_FIELDS'
        
        # Validar nombre
        name = str(record['name']).strip()
        if len(name) < 2:
            errors.append("Nombre debe tener al menos 2 caracteres")
        elif len(name) > 255:
            errors.append("Nombre no puede exceder 255 caracteres")
        elif not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\.]+$', name):
            errors.append("Nombre contiene caracteres inválidos")
        
        # Validar id si está presente
        if 'id' in record and record['id'] is not None:
            try:
                dept_id = int(record['id'])
                if dept_id <= 0:
                    errors.append("id debe ser un entero positivo")
                elif Department.objects.filter(id=dept_id).exists():
                    errors.append(f"id {dept_id} ya existe en la base de datos")
            except (ValueError, TypeError):
                errors.append("id debe ser un entero válido")
        
        if errors:
            return False, '; '.join(errors), 'VALIDATION_ERROR'
        
        return True, None, None
    
    @staticmethod
    def validate_job(record, record_id=None):
        """
        Valida un registro de job
        
        Args:
            record: Diccionario con los datos del registro
            record_id: ID del registro (opcional)
            
        Returns:
            tuple: (is_valid, error_message, error_type)
        """
        errors = []
        
        # Validar campos requeridos
        if 'name' not in record or not record['name'] or str(record['name']).strip() == '':
            errors.append("Campo requerido 'name' está vacío o faltante")
        
        if errors:
            return False, '; '.join(errors), 'MISSING_REQUIRED_FIELDS'
        
        # Validar nombre
        name = str(record['name']).strip()
        if len(name) < 2:
            errors.append("Nombre debe tener al menos 2 caracteres")
        elif len(name) > 255:
            errors.append("Nombre no puede exceder 255 caracteres")
        elif not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\.]+$', name):
            errors.append("Nombre contiene caracteres inválidos")
        
        # Validar id si está presente
        if 'id' in record and record['id'] is not None:
            try:
                job_id = int(record['id'])
                if job_id <= 0:
                    errors.append("id debe ser un entero positivo")
                elif Job.objects.filter(id=job_id).exists():
                    errors.append(f"id {job_id} ya existe en la base de datos")
            except (ValueError, TypeError):
                errors.append("id debe ser un entero válido")
        
        if errors:
            return False, '; '.join(errors), 'VALIDATION_ERROR'
        
        return True, None, None


class DataQualityLogger:
    """Logger para registrar transacciones que no cumplen las reglas"""
    
    @staticmethod
    def log_failed_transaction(table_name, record, error_message, error_type, record_id=None):
        """
        Registra una transacción que falló las validaciones
        
        Args:
            table_name: Nombre de la tabla
            record: Datos del registro que falló
            error_message: Mensaje de error
            error_type: Tipo de error
            record_id: ID del registro (opcional)
        """
        try:
            # Limpiar datos para serialización JSON
            cleaned_record = clean_data_for_json(record)
            
            DataMigrationLog.objects.create(
                table_name=table_name,
                record_id=str(record_id) if record_id else None,
                error_type=error_type,
                error_message=error_message,
                raw_data=cleaned_record
            )
            logger.warning(f"Registro fallido en {table_name}: {error_message}")
        except Exception as e:
            logger.error(f"Error registrando transacción fallida: {e}")
    
    @staticmethod
    def log_batch_results(table_name, total_records, valid_records, failed_records):
        """
        Registra un resumen de procesamiento de lote
        
        Args:
            table_name: Nombre de la tabla
            total_records: Total de registros procesados
            valid_records: Registros válidos
            failed_records: Registros que fallaron
        """
        try:
            if failed_records > 0:
                batch_data = {
                    'total_records': total_records,
                    'valid_records': valid_records,
                    'failed_records': failed_records,
                    'success_rate': round((valid_records / total_records) * 100, 2) if total_records > 0 else 0
                }
                
                # Limpiar datos para serialización JSON
                cleaned_data = clean_data_for_json(batch_data)
                
                DataMigrationLog.objects.create(
                    table_name=table_name,
                    record_id=None,
                    error_type='BATCH_SUMMARY',
                    error_message=f"Lote procesado: {valid_records}/{total_records} registros válidos, {failed_records} fallaron validación",
                    raw_data=cleaned_data
                )
            logger.info(f"Lote {table_name}: {valid_records}/{total_records} registros válidos")
        except Exception as e:
            logger.error(f"Error registrando resumen de lote: {e}")


def validate_and_log_record(table_name, record, record_id=None):
    """
    Función de conveniencia para validar y loggear un registro
    
    Args:
        table_name: Nombre de la tabla
        record: Datos del registro
        record_id: ID del registro (opcional)
        
    Returns:
        bool: True si el registro es válido, False si no
    """
    validator = DataQualityValidator()
    logger = DataQualityLogger()
    
    # Seleccionar validador según la tabla
    if table_name == 'hired_employees':
        is_valid, error_message, error_type = validator.validate_hired_employee(record, record_id)
    elif table_name == 'departments':
        is_valid, error_message, error_type = validator.validate_department(record, record_id)
    elif table_name == 'jobs':
        is_valid, error_message, error_type = validator.validate_job(record, record_id)
    else:
        logger.log_failed_transaction(
            table_name, record, f"Tabla desconocida: {table_name}", 'UNKNOWN_TABLE', record_id
        )
        return False
    
    # Si no es válido, loggear el error
    if not is_valid:
        logger.log_failed_transaction(table_name, record, error_message, error_type, record_id)
    
    return is_valid
