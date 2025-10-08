"""
Configuración del Django Admin para gestión de API Keys y seguridad
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import APIKey, SecurityLog, RateLimit, DataMigrationLog


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = [
        'name', 
        'user_display', 
        'is_active_display', 
        'permissions_display',
        'created_at', 
        'last_used',
        'expires_at_display'
    ]
    list_filter = [
        'is_active', 
        'can_ingest', 
        'can_backup', 
        'can_restore', 
        'can_view_logs', 
        'can_trigger_migration',
        'created_at'
    ]
    search_fields = ['name', 'user__username', 'user__email']
    readonly_fields = [
        'key_hash', 
        'created_at', 
        'last_used',
        'api_key_display'
    ]
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('name', 'user', 'is_active', 'expires_at')
        }),
        ('Permisos', {
            'fields': (
                'can_ingest', 
                'can_backup', 
                'can_restore', 
                'can_view_logs', 
                'can_trigger_migration'
            ),
            'description': 'Selecciona los permisos que tendrá esta API key'
        }),
        ('Información del Sistema', {
            'fields': ('key_hash', 'created_at', 'last_used', 'api_key_display'),
            'classes': ('collapse',),
            'description': 'Información técnica de la API key'
        })
    )
    
    def user_display(self, obj):
        """Muestra el usuario asociado"""
        if obj.user:
            return obj.user.username
        return "Sin usuario"
    user_display.short_description = 'Usuario'
    
    def is_active_display(self, obj):
        """Muestra el estado con colores"""
        if obj.is_valid():
            return format_html('<span style="color: green;">✓ Activa</span>')
        elif obj.is_expired():
            return format_html('<span style="color: red;">✗ Expirada</span>')
        else:
            return format_html('<span style="color: orange;">✗ Inactiva</span>')
    is_active_display.short_description = 'Estado'
    
    def permissions_display(self, obj):
        """Muestra los permisos de forma compacta"""
        perms = []
        if obj.can_ingest:
            perms.append('Ingest')
        if obj.can_backup:
            perms.append('Backup')
        if obj.can_restore:
            perms.append('Restore')
        if obj.can_view_logs:
            perms.append('Logs')
        if obj.can_trigger_migration:
            perms.append('Migration')
        
        return ', '.join(perms) if perms else 'Sin permisos'
    permissions_display.short_description = 'Permisos'
    
    def expires_at_display(self, obj):
        """Muestra la fecha de expiración"""
        if obj.expires_at:
            return obj.expires_at.strftime('%Y-%m-%d %H:%M')
        return "Nunca"
    expires_at_display.short_description = 'Expira'
    
    def api_key_display(self, obj):
        """Muestra la API key (solo al crear)"""
        if obj.pk:  # Si ya existe en la BD
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠️ API Key ya fue mostrada</span><br>'
                '<small>La API key solo se muestra una vez por seguridad</small>'
            )
        return "Se mostrará al guardar"
    api_key_display.short_description = 'API Key'
    
    def save_model(self, request, obj, form, change):
        """Maneja la creación de API keys"""
        if not change:  # Solo al crear nueva API key
            api_key = APIKey.generate_key()
            obj.key_hash = APIKey.hash_key(api_key)
            super().save_model(request, obj, form, change)
            
            # Mostrar la key al admin
            self.message_user(
                request, 
                format_html(
                    '<div style="background: #d4edda; border: 1px solid #c3e6cb; '
                    'color: #155724; padding: 10px; border-radius: 4px; margin: 10px 0;">'
                    '<strong>✅ API Key creada exitosamente!</strong><br>'
                    '<strong>API Key:</strong> <code style="background: #f8f9fa; padding: 2px 4px; '
                    'border-radius: 3px;">{}</code><br>'
                    '<span style="color: #856404;">⚠️ <strong>IMPORTANTE:</strong> '
                    'Guarda esta API key de forma segura. No se puede recuperar.</span>'
                    '</div>',
                    api_key
                ),
                level='SUCCESS'
            )
        else:
            super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        """Optimiza las consultas"""
        return super().get_queryset(request).select_related('user')


@admin.register(SecurityLog)
class SecurityLogAdmin(admin.ModelAdmin):
    list_display = [
        'timestamp', 
        'event_type_display', 
        'api_key_name', 
        'ip_address', 
        'endpoint',
        'method'
    ]
    list_filter = [
        'event_type', 
        'method',
        'timestamp'
    ]
    search_fields = ['api_key_name', 'ip_address', 'endpoint']
    readonly_fields = [
        'timestamp', 
        'event_type', 
        'api_key_name', 
        'ip_address', 
        'user_agent', 
        'endpoint', 
        'method', 
        'details_display'
    ]
    date_hierarchy = 'timestamp'
    ordering = ['-timestamp']
    
    def event_type_display(self, obj):
        """Muestra el tipo de evento con colores"""
        colors = {
            'AUTH_SUCCESS': 'green',
            'AUTH_FAILED': 'red',
            'AUTH_MISSING': 'orange',
            'AUTH_INVALID': 'red',
            'AUTH_EXPIRED': 'orange',
            'RATE_LIMIT': 'red',
            'INVALID_INPUT': 'orange',
            'UNAUTHORIZED_ACCESS': 'red'
        }
        color = colors.get(obj.event_type, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_event_type_display()
        )
    event_type_display.short_description = 'Tipo de Evento'
    
    def details_display(self, obj):
        """Muestra los detalles de forma legible"""
        if obj.details:
            import json
            try:
                details = json.dumps(obj.details, indent=2, ensure_ascii=False)
                return format_html('<pre style="background: #f8f9fa; padding: 10px; border-radius: 4px;">{}</pre>', details)
            except:
                return str(obj.details)
        return "Sin detalles"
    details_display.short_description = 'Detalles'
    
    def has_add_permission(self, request):
        """No permitir crear logs manualmente"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """No permitir editar logs"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Solo superusuarios pueden eliminar logs"""
        return request.user.is_superuser


@admin.register(RateLimit)
class RateLimitAdmin(admin.ModelAdmin):
    list_display = [
        'api_key_name', 
        'endpoint', 
        'request_count', 
        'window_start', 
        'last_request'
    ]
    list_filter = ['endpoint', 'window_start']
    search_fields = ['api_key__name', 'endpoint']
    readonly_fields = [
        'api_key', 
        'endpoint', 
        'request_count', 
        'window_start', 
        'last_request'
    ]
    
    def api_key_name(self, obj):
        """Muestra el nombre de la API key"""
        return obj.api_key.name
    api_key_name.short_description = 'API Key'
    
    def has_add_permission(self, request):
        """No permitir crear rate limits manualmente"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """No permitir editar rate limits"""
        return False


@admin.register(DataMigrationLog)
class DataMigrationLogAdmin(admin.ModelAdmin):
    list_display = [
        'timestamp', 
        'table_name', 
        'error_type', 
        'record_id',
        'error_message_short'
    ]
    list_filter = ['table_name', 'error_type', 'timestamp']
    search_fields = ['table_name', 'error_message', 'record_id']
    readonly_fields = [
        'timestamp', 
        'table_name', 
        'record_id', 
        'error_type', 
        'error_message', 
        'raw_data_display'
    ]
    date_hierarchy = 'timestamp'
    ordering = ['-timestamp']
    
    def error_message_short(self, obj):
        """Muestra un resumen del error"""
        if len(obj.error_message) > 100:
            return obj.error_message[:100] + "..."
        return obj.error_message
    error_message_short.short_description = 'Error'
    
    def raw_data_display(self, obj):
        """Muestra los datos raw de forma legible"""
        if obj.raw_data:
            import json
            try:
                data = json.dumps(obj.raw_data, indent=2, ensure_ascii=False)
                return format_html('<pre style="background: #f8f9fa; padding: 10px; border-radius: 4px;">{}</pre>', data)
            except:
                return str(obj.raw_data)
        return "Sin datos"
    raw_data_display.short_description = 'Datos Raw'
    
    def has_add_permission(self, request):
        """No permitir crear logs manualmente"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """No permitir editar logs"""
        return False


# Personalizar el título del admin
admin.site.site_header = "Data Migration POC - Administración"
admin.site.site_title = "Data Migration Admin"
admin.site.index_title = "Panel de Administración"