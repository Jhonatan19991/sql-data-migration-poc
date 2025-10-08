from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import User
import re
import secrets
import hashlib


class Department(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    
    class Meta:
        db_table = 'departments'
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'
    
    def __str__(self):
        return f"{self.id}: {self.name}"


class Job(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    
    class Meta:
        db_table = 'jobs'
        verbose_name = 'Job'
        verbose_name_plural = 'Jobs'
    
    def __str__(self):
        return f"{self.id}: {self.name}"


class HiredEmployee(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    datetime = models.DateTimeField()
    department = models.ForeignKey(Department, on_delete=models.CASCADE, db_column='department_id')
    job = models.ForeignKey(Job, on_delete=models.CASCADE, db_column='job_id')
    
    class Meta:
        db_table = 'hired_employees'
        verbose_name = 'Hired Employee'
        verbose_name_plural = 'Hired Employees'
        ordering = ['id']
    
    def __str__(self):
        return f"{self.id}: {self.name} - {self.department.name} - {self.job.name}"
    
    def clean(self):
        # Validaciones de calidad de datos
        if not self.name or self.name.strip() == '':
            raise ValidationError({'name': 'Name is required and cannot be empty'})
        
        if not self.datetime:
            raise ValidationError({'datetime': 'Datetime is required'})
        
        if not self.department_id:
            raise ValidationError({'department': 'Department is required'})
        
        if not self.job_id:
            raise ValidationError({'job': 'Job is required'})
        
        # Validar formato de fecha ISO-8601
        if self.datetime and self.datetime > timezone.now():
            raise ValidationError({'datetime': 'Datetime cannot be in the future'})
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class DataMigrationLog(models.Model):
    """Log para registrar errores de migración y validación"""
    timestamp = models.DateTimeField(auto_now_add=True)
    table_name = models.CharField(max_length=100)
    record_id = models.CharField(max_length=100, null=True, blank=True)
    error_type = models.CharField(max_length=50)
    error_message = models.TextField()
    raw_data = models.JSONField(null=True, blank=True)
    
    class Meta:
        db_table = 'data_migration_logs'
        verbose_name = 'Migration Log'
        verbose_name_plural = 'Migration Logs'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.timestamp}: {self.table_name} - {self.error_type}"


class APIKey(models.Model):
    """Modelo para manejar API Keys de autenticación"""
    name = models.CharField(max_length=100, help_text="Nombre descriptivo de la API key")
    key_hash = models.CharField(max_length=64, unique=True, help_text="Hash SHA-256 de la API key")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Fecha de expiración (opcional)")
    
    # Permisos específicos
    can_ingest = models.BooleanField(default=True, help_text="Puede usar endpoint de ingest")
    can_backup = models.BooleanField(default=True, help_text="Puede crear backups")
    can_restore = models.BooleanField(default=True, help_text="Puede restaurar desde backups")
    can_view_logs = models.BooleanField(default=True, help_text="Puede ver logs de migración")
    can_trigger_migration = models.BooleanField(default=False, help_text="Puede disparar migraciones")
    
    class Meta:
        db_table = 'api_keys'
        verbose_name = 'API Key'
        verbose_name_plural = 'API Keys'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"
    
    @classmethod
    def generate_key(cls):
        """Genera una nueva API key segura"""
        return secrets.token_urlsafe(32)
    
    @classmethod
    def hash_key(cls, key):
        """Genera hash SHA-256 de la API key"""
        return hashlib.sha256(key.encode()).hexdigest()
    
    def is_expired(self):
        """Verifica si la API key ha expirado"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False
    
    def is_valid(self):
        """Verifica si la API key es válida (activa y no expirada)"""
        return self.is_active and not self.is_expired()


class SecurityLog(models.Model):
    """Log para registrar eventos de seguridad"""
    timestamp = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField(max_length=50, choices=[
        ('AUTH_SUCCESS', 'Autenticación exitosa'),
        ('AUTH_FAILED', 'Autenticación fallida'),
        ('AUTH_MISSING', 'API key faltante'),
        ('AUTH_INVALID', 'API key inválida'),
        ('AUTH_EXPIRED', 'API key expirada'),
        ('RATE_LIMIT', 'Rate limit excedido'),
        ('INVALID_INPUT', 'Input inválido'),
        ('UNAUTHORIZED_ACCESS', 'Acceso no autorizado'),
    ])
    api_key_name = models.CharField(max_length=100, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    endpoint = models.CharField(max_length=200)
    method = models.CharField(max_length=10)
    details = models.JSONField(null=True, blank=True)
    
    class Meta:
        db_table = 'security_logs'
        verbose_name = 'Security Log'
        verbose_name_plural = 'Security Logs'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.timestamp}: {self.event_type} - {self.endpoint}"


class RateLimit(models.Model):
    """Modelo para manejar rate limiting por API key"""
    api_key = models.ForeignKey(APIKey, on_delete=models.CASCADE)
    endpoint = models.CharField(max_length=200)
    request_count = models.IntegerField(default=0)
    window_start = models.DateTimeField(auto_now_add=True)
    last_request = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'rate_limits'
        unique_together = ['api_key', 'endpoint']
    
    def __str__(self):
        return f"{self.api_key.name} - {self.endpoint}: {self.request_count}"
