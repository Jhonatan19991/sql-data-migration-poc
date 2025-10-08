from django.urls import path
from . import views

urlpatterns = [
    path('ingest/', views.ingest, name='ingest'),
    path('backup/<str:table>/', views.backup_table, name='backup_table'),
    path('restore/<str:table>/', views.restore_table, name='restore_table'),
    path('batch-transaction/', views.batch_transaction, name='batch_transaction'),
    path('migration-logs/', views.migration_logs, name='migration_logs'),
    path('security-logs/', views.security_logs, name='security_logs'),
    path('health/', views.health_check, name='health_check'),
    path('trigger-migration/', views.trigger_migration, name='trigger_migration'),
    # Métricas para PowerBI
    path('metrics/employees-by-quarter/', views.employees_by_quarter, name='employees_by_quarter'),
    path('metrics/departments-above-average/', views.departments_above_average, name='departments_above_average'),
]
