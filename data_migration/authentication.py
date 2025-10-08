"""
Sistema de autenticación y autorización para la API
"""

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from django.utils import timezone
from django.core.cache import cache
import logging

from .models import APIKey, SecurityLog, RateLimit

logger = logging.getLogger(__name__)


class APIKeyAuthentication(BaseAuthentication):
    """
    Autenticación basada en API Keys
    """
    
    def authenticate(self, request):
        api_key = self.get_api_key(request)
        if not api_key:
            self.log_security_event(request, 'AUTH_MISSING', 'API key missing')
            return None
        
        try:
            api_key_obj = self.validate_api_key(api_key)
            if api_key_obj:
                # Actualizar último uso
                api_key_obj.last_used = timezone.now()
                api_key_obj.save(update_fields=['last_used'])
                
                self.log_security_event(request, 'AUTH_SUCCESS', 'Authentication successful', api_key_obj.name)
                return (api_key_obj, None)
            else:
                self.log_security_event(request, 'AUTH_INVALID', 'Invalid API key')
                raise AuthenticationFailed('Invalid API key')
                
        except Exception as e:
            self.log_security_event(request, 'AUTH_FAILED', f'Authentication failed: {str(e)}')
            raise AuthenticationFailed('Authentication failed')
    
    def get_api_key(self, request):
        """
        Extrae la API key del header Authorization o X-API-Key
        """
        # Buscar en header Authorization: Bearer <key>
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        
        # Buscar en header X-API-Key
        return request.META.get('HTTP_X_API_KEY')
    
    def validate_api_key(self, api_key):
        """
        Valida la API key contra la base de datos
        """
        if not api_key:
            return None
        
        # Generar hash de la key proporcionada
        key_hash = APIKey.hash_key(api_key)
        
        try:
            api_key_obj = APIKey.objects.get(key_hash=key_hash)
            
            # Verificar si es válida
            if not api_key_obj.is_valid():
                if api_key_obj.is_expired():
                    self.log_security_event(None, 'AUTH_EXPIRED', 'API key expired', api_key_obj.name)
                return None
            
            return api_key_obj
            
        except APIKey.DoesNotExist:
            return None
    
    def log_security_event(self, request, event_type, message, api_key_name=None):
        """
        Registra eventos de seguridad
        """
        try:
            SecurityLog.objects.create(
                event_type=event_type,
                api_key_name=api_key_name,
                ip_address=self.get_client_ip(request) if request else None,
                user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
                endpoint=request.path if request else '',
                method=request.method if request else '',
                details={'message': message}
            )
        except Exception as e:
            logger.error(f"Error logging security event: {e}")
    
    def get_client_ip(self, request):
        """
        Obtiene la IP real del cliente
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class HasAPIPermission(BasePermission):
    """
    Permiso personalizado para verificar permisos específicos de API
    """
    
    def __init__(self, required_permission):
        self.required_permission = required_permission
    
    def has_permission(self, request, view):
        if not hasattr(request, 'user') or not request.user:
            return False
        
        # request.user es un objeto APIKey
        api_key = request.user
        
        # Verificar el permiso específico
        if hasattr(api_key, self.required_permission):
            return getattr(api_key, self.required_permission)
        
        return False


class CanIngestPermission(HasAPIPermission):
    def __init__(self):
        super().__init__('can_ingest')


class CanBackupPermission(HasAPIPermission):
    def __init__(self):
        super().__init__('can_backup')


class CanRestorePermission(HasAPIPermission):
    def __init__(self):
        super().__init__('can_restore')


class CanViewLogsPermission(HasAPIPermission):
    def __init__(self):
        super().__init__('can_view_logs')


class CanTriggerMigrationPermission(HasAPIPermission):
    def __init__(self):
        super().__init__('can_trigger_migration')


class RateLimitPermission(BasePermission):
    """
    Permiso para implementar rate limiting
    """
    
    def __init__(self, requests_per_minute=60):
        self.requests_per_minute = requests_per_minute
    
    def has_permission(self, request, view):
        if not hasattr(request, 'user') or not request.user:
            return False
        
        api_key = request.user
        endpoint = request.path
        
        # Verificar rate limit
        return self.check_rate_limit(api_key, endpoint, request)
    
    def check_rate_limit(self, api_key, endpoint, request):
        """
        Verifica si el request está dentro del rate limit
        """
        try:
            # Usar cache para rate limiting más eficiente
            cache_key = f"rate_limit_{api_key.id}_{endpoint}"
            current_count = cache.get(cache_key, 0)
            
            if current_count >= self.requests_per_minute:
                self.log_security_event(request, 'RATE_LIMIT', 
                    f'Rate limit exceeded: {current_count}/{self.requests_per_minute}')
                return False
            
            # Incrementar contador
            cache.set(cache_key, current_count + 1, 60)  # Expira en 60 segundos
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return True  # En caso de error, permitir el acceso
    
    def log_security_event(self, request, event_type, message):
        """
        Registra eventos de seguridad
        """
        try:
            SecurityLog.objects.create(
                event_type=event_type,
                api_key_name=request.user.name if hasattr(request, 'user') and request.user else None,
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                endpoint=request.path,
                method=request.method,
                details={'message': message}
            )
        except Exception as e:
            logger.error(f"Error logging security event: {e}")
    
    def get_client_ip(self, request):
        """
        Obtiene la IP real del cliente
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
