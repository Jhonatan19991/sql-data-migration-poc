"""
Middleware de seguridad para validación y sanitización de entrada
"""

import json
import logging
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.core.exceptions import ValidationError
import re

logger = logging.getLogger(__name__)


class SecurityMiddleware(MiddlewareMixin):
    """
    Middleware para validación de seguridad y sanitización de entrada
    """
    
    def process_request(self, request):
        """
        Procesa la request antes de que llegue a la vista
        """
        try:
            # Validar tamaño de request
            if hasattr(request, 'content_length') and request.content_length:
                max_size = 10 * 1024 * 1024  # 10MB
                if request.content_length > max_size:
                    logger.warning(f"Request too large: {request.content_length} bytes from {self.get_client_ip(request)}")
                    return JsonResponse({
                        'error': 'Request too large',
                        'message': f'Request size exceeds maximum allowed size of {max_size} bytes'
                    }, status=413)
            
            # Validar User-Agent
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            if self.is_suspicious_user_agent(user_agent):
                logger.warning(f"Suspicious User-Agent: {user_agent} from {self.get_client_ip(request)}")
                # No bloquear, solo loggear
            
            # Validar headers maliciosos
            if self.has_malicious_headers(request):
                logger.warning(f"Malicious headers detected from {self.get_client_ip(request)}")
                return JsonResponse({
                    'error': 'Invalid request',
                    'message': 'Request contains invalid headers'
                }, status=400)
            
            return None
            
        except Exception as e:
            logger.error(f"Error in security middleware: {e}")
            return None
    
    def process_response(self, request, response):
        """
        Procesa la response antes de enviarla al cliente
        """
        try:
            # Agregar headers de seguridad
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
            response['X-XSS-Protection'] = '1; mode=block'
            response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
            
            # Solo para APIs, no para archivos estáticos
            if request.path.startswith('/api/'):
                response['Content-Security-Policy'] = "default-src 'self'"
            
            return response
            
        except Exception as e:
            logger.error(f"Error adding security headers: {e}")
            return response
    
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
    
    def is_suspicious_user_agent(self, user_agent):
        """
        Detecta User-Agents sospechosos
        """
        suspicious_patterns = [
            r'sqlmap',
            r'nmap',
            r'nikto',
            r'havij',
            r'python-requests',
            r'curl',
            r'wget',
            r'bot',
            r'crawler',
            r'spider'
        ]
        
        user_agent_lower = user_agent.lower()
        for pattern in suspicious_patterns:
            if re.search(pattern, user_agent_lower):
                return True
        
        return False
    
    def has_malicious_headers(self, request):
        """
        Detecta headers maliciosos
        """
        malicious_headers = [
            'HTTP_X_FORWARDED_FOR',
            'HTTP_X_REAL_IP',
            'HTTP_X_CLUSTER_CLIENT_IP',
            'HTTP_X_FORWARDED',
            'HTTP_FORWARDED_FOR',
            'HTTP_FORWARDED',
            'HTTP_CLIENT_IP',
            'HTTP_CF_CONNECTING_IP',
            'HTTP_X_FORWARDED_PROTO',
            'HTTP_X_FORWARDED_HOST',
            'HTTP_X_FORWARDED_SERVER'
        ]
        
        # Verificar si hay headers de proxy sospechosos
        for header in malicious_headers:
            if header in request.META:
                value = request.META[header]
                # Verificar si contiene IPs múltiples o caracteres sospechosos
                if ',' in value or ';' in value or len(value) > 50:
                    return True
        
        return False


class InputValidationMiddleware(MiddlewareMixin):
    """
    Middleware para validación y sanitización de entrada JSON
    """
    
    def process_request(self, request):
        """
        Valida y sanitiza el contenido JSON de la request
        """
        try:
            # Solo procesar requests POST/PUT/PATCH con JSON
            if request.method in ['POST', 'PUT', 'PATCH'] and request.content_type == 'application/json':
                # Leer el body
                body = request.body.decode('utf-8')
                
                # Validar tamaño
                if len(body) > 1024 * 1024:  # 1MB
                    logger.warning(f"JSON payload too large: {len(body)} bytes")
                    return JsonResponse({
                        'error': 'Payload too large',
                        'message': 'JSON payload exceeds maximum size'
                    }, status=413)
                
                # Validar JSON
                try:
                    data = json.loads(body)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON: {e}")
                    return JsonResponse({
                        'error': 'Invalid JSON',
                        'message': 'Request body contains invalid JSON'
                    }, status=400)
                
                # Sanitizar datos
                sanitized_data = self.sanitize_data(data)
                
                # Reemplazar el body con datos sanitizados
                request._body = json.dumps(sanitized_data).encode('utf-8')
                
            return None
            
        except Exception as e:
            logger.error(f"Error in input validation middleware: {e}")
            return None
    
    def sanitize_data(self, data):
        """
        Sanitiza los datos de entrada
        """
        if isinstance(data, dict):
            return {key: self.sanitize_data(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self.sanitize_data(item) for item in data]
        elif isinstance(data, str):
            return self.sanitize_string(data)
        else:
            return data
    
    def sanitize_string(self, text):
        """
        Sanitiza strings de entrada
        """
        if not isinstance(text, str):
            return text
        
        # Remover caracteres de control
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        
        # Limitar longitud
        if len(text) > 10000:  # 10KB por string
            text = text[:10000]
        
        # Remover scripts potencialmente maliciosos
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
        text = re.sub(r'vbscript:', '', text, flags=re.IGNORECASE)
        
        return text.strip()
