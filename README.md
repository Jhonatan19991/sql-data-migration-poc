# SQL Data Migration PoC

Prueba de Concepto (PoC) para migración masiva de datos con Django, MinIO y PostgreSQL.

## Arquitectura

Este proyecto implementa una solución completa para migración de datos que incluye:

- **Django REST API** para recibir transacciones en lotes
- **MinIO** como almacenamiento S3-compatible para datos intermedios
- **PostgreSQL** como base de datos de destino con migración optimizada
- **Docker Compose** para orquestación de servicios

## Características

### 1. Migración de Datos Históricos
- Carga de archivos CSV en lotes de exactamente 1000 registros
- Almacenamiento intermedio en MinIO en formato CSV
- Migración automática de MinIO a PostgreSQL usando COPY optimizado
- Limpieza completa con TRUNCATE para evitar duplicados

### 2. API REST para Datos en Línea
- Endpoint `/api/batch-transaction/` para recibir lotes de 1-1000 registros
- Validación automática contra diccionario de datos
- Soporte para múltiples tablas (hired_employees, departments, jobs)
- Aplicación de reglas de calidad de datos

### 3. Monitoreo y Logging
- Logs detallados de errores de migración
- Endpoint `/api/migration-logs/` para consultar logs
- Health check en `/api/health/`

## Estructura de Datos

### hired_employees.csv
- `id` (INTEGER): Identificador del empleado
- `name` (STRING): Nombre y apellido del empleado
- `datetime` (STRING): Fecha/hora de contratación (ISO-8601)
- `department_id` (INTEGER): Identificador del departamento
- `job_id` (INTEGER): Identificador del cargo

### departments.csv
- `id` (INTEGER): Identificador del departamento
- `name` (STRING): Nombre del departamento

### jobs.csv
- `id` (INTEGER): Identificador del cargo
- `name` (STRING): Nombre del cargo

## Instalación y Uso

### Prerrequisitos
- Docker
- Docker Compose

### Pasos de Instalación

1. **Clonar el repositorio**
```bash
git clone <repository-url>
cd sql-data-migration-poc
```

2. **Colocar archivos CSV en la carpeta Data/**
```
Data/
├── hired_employees.csv
├── departments.csv
└── jobs.csv
```

3. **Ejecutar con Docker Compose (Versión TRUNCATE - Recomendada)**
```bash
docker-compose up --build
```


### ⚡ Optimizaciones de Rendimiento

La versión TRUNCATE incluye:
- **TRUNCATE + COPY de PostgreSQL**: Máximo rendimiento sin conflictos
- **Limpieza completa**: TRUNCATE elimina todos los datos previos
- **Batch size exacto**: 1000 registros por lote (requisito específico)
- **Eliminación robusta de duplicados**: Múltiples pasos de limpieza
- **Tiempo estimado**: 1-2 minutos para 765,000 registros

### Servicios Disponibles

- **Django API**: http://localhost:8000
- **MinIO Console**: http://localhost:9001 (admin/password)
- **PostgreSQL**: localhost:5432 (poc/poc_pass)

## API Endpoints

### POST /api/batch-transaction/
Recibe lotes de transacciones para insertar en la base de datos.

**Request Body:**
```json
{
    "table_name": "hired_employees",
    "records": [
        {
            "id": 1,
            "name": "John Doe",
            "datetime": "2023-01-01T10:00:00",
            "department_id": 1,
            "job_id": 1
        }
    ]
}
```

**Response:**
```json
{
    "message": "Successfully processed 1 records",
    "success_count": 1,
    "error_count": 0,
    "errors": []
}
```

### GET /api/migration-logs/
Consulta los logs de migración más recientes.

### GET /api/health/
Health check del servicio.

### POST /api/trigger-migration/
Dispara manualmente la migración completa.

## Configuración

### Variables de Entorno
- `POSTGRES_DB`: Nombre de la base de datos PostgreSQL
- `POSTGRES_USER`: Usuario de PostgreSQL
- `POSTGRES_PASSWORD`: Contraseña de PostgreSQL
- `MINIO_ENDPOINT`: URL del endpoint de MinIO
- `MINIO_ACCESS_KEY`: Clave de acceso de MinIO
- `MINIO_SECRET_KEY`: Clave secreta de MinIO

### Configuración de Base de Datos
La configuración de PostgreSQL se maneja a través de Django settings:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'poc',
        'USER': 'poc',
        'PASSWORD': 'poc_pass',
        'HOST': 'db',
        'PORT': '5432',
    }
}
```

## Flujo de Migración

1. **Inicio del contenedor**: Se ejecuta automáticamente la migración TRUNCATE
2. **Carga a MinIO**: Los CSVs se cargan completos a MinIO en formato CSV
3. **Limpieza con TRUNCATE**: Se limpia completamente cada tabla antes de cargar
4. **Migración a PostgreSQL**: COPY optimizado migra los datos de MinIO a PostgreSQL
5. **API lista**: El servicio REST queda disponible para nuevas transacciones

## Validaciones de Calidad

- Todos los campos son obligatorios
- Validación de formato de fecha ISO-8601
- Verificación de existencia de departamentos y trabajos
- Registro de errores en logs detallados

## Desarrollo

### Estructura del Proyecto
```
├── data_migration/          # App Django principal
│   ├── management/commands/ # Comandos de Django
│   ├── migrations/         # Migraciones de base de datos
│   ├── models.py          # Modelos de datos
│   ├── serializers.py     # Serializers de API
│   ├── services.py        # Lógica de negocio
│   └── views.py           # Vistas de API
├── migration_poc/         # Configuración Django
├── Data/                  # Archivos CSV de entrada
├── .dlt/                  # Configuración dlt
└── docker-compose.yml     # Orquestación de servicios
```

## Pruebas

### Prueba Rápida
```bash
python test_api.py
```

### Prueba Completa
```bash
python test_complete.py
```

### Pruebas Manuales

1. **Health Check**
```bash
curl http://localhost:8000/api/health/
```

2. **Enviar lote de departamentos**
```bash
curl -X POST http://localhost:8000/api/batch-transaction/ \
  -H "Content-Type: application/json" \
  -d '{
    "table_name": "departments",
    "records": [
      {"id": 100, "name": "Test Department"}
    ]
  }'
```

3. **Consultar logs de migración**
```bash
curl http://localhost:8000/api/migration-logs/
```

4. **Crear backup de una tabla**
```bash
curl -X POST http://localhost:8000/api/backup/hired_employees/
```

5. **Restaurar tabla desde backup específico**
```bash
curl -X POST http://localhost:8000/api/restore/hired_employees/ \
  -H "Content-Type: application/json" \
  -d '{
    "backup_path": "backups/hired_employees/20251007T123456/",
    "chunk_size": 1000
  }'
```

6. **Restaurar tabla desde el último backup (automático)**
```bash
curl -X POST http://localhost:8000/api/restore/hired_employees/ \
  -H "Content-Type: application/json" \
  -d '{
    "chunk_size": 1000
  }'
```

## Backup y Restauración

### Crear Backup
El sistema permite crear backups en formato Parquet de cualquier tabla:

**API Endpoint:**
```bash
POST /api/backup/{table}/
```

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/backup/hired_employees/
```

**Comando Django:**
```bash
python manage.py run_backup_parquet hired_employees
```

### Restaurar desde Backup
Restaura una tabla completa desde un backup Parquet almacenado en MinIO:

**API Endpoint:**
```bash
POST /api/restore/{table}/
```

**Body:**
```json
{
  "backup_path": "backups/hired_employees/20251007T123456/",  // opcional, si no se especifica usa el último backup
  "chunk_size": 1000
}
```

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/api/restore/hired_employees/ \
  -H "Content-Type: application/json" \
  -d '{
    "backup_path": "backups/hired_employees/20251007T123456/",
    "chunk_size": 1000
  }'
```

**Comando Django:**
```bash
# Restaurar desde backup específico
python manage.py run_restore_parquet hired_employees "backups/hired_employees/20251007T123456/" --chunk-size 1000

# Restaurar desde el último backup (automático)
python manage.py run_restore_parquet hired_employees --chunk-size 1000
```

### Características del Sistema de Backup/Restore

- **Formato**: Parquet con compresión Snappy
- **Almacenamiento**: MinIO (S3-compatible)
- **Procesamiento**: En lotes de 1000 registros (configurable)
- **Limpieza**: La tabla se trunca antes de restaurar
- **Manejo de IDs**: Soporte para IDs autoincrementales en `hired_employees`
- **Auto-detección**: Si no se especifica backup_path, usa automáticamente el último backup
- **Logging**: Logs detallados del proceso de backup/restore

## Monitoreo

### Logs
Los logs se almacenan en:
- `logs/migration.log`: Logs generales del sistema
- `logs/error.log`: Logs de errores

### MinIO Console
Accede a http://localhost:9001 para ver los archivos almacenados:
- Usuario: `admin`
- Contraseña: `password`

### Base de Datos
Conecta a PostgreSQL para verificar los datos:
- Host: `localhost`
- Puerto: `5432`
- Base de datos: `poc`
- Usuario: `poc`
- Contraseña: `poc_pass`

## Seguridad de la API

### 🚀 Inicialización Rápida

#### **Opción 1: Script Automático (Recomendado)**
```bash
# 1. Acceder al contenedor
docker-compose exec web bash

# 2. Ejecutar script de inicialización
./init_security.sh
```

#### **Opción 2: Pasos Manuales**
```bash
# 1. Acceder al contenedor
docker-compose exec web bash

# 2. Crear migraciones y aplicar
python manage.py makemigrations data_migration
python manage.py migrate

# 3. Crear superusuario
python manage.py create_admin_user

# 4. Crear API keys por defecto
python manage.py init_security --create-default-keys
```

### 🔐 Sistema de Autenticación

La API utiliza un sistema de autenticación basado en **API Keys** con permisos granulares:

#### **Crear API Key**
```bash
# Crear API key básica
python manage.py manage_api_keys create "Mi API Key"

# Crear API key con permisos específicos
python manage.py manage_api_keys create "Admin Key" \
  --can-trigger-migration \
  --expires-days 30

# Crear API key para solo lectura
python manage.py manage_api_keys create "Read Only Key" \
  --can-ingest \
  --can-backup \
  --can-restore \
  --can-view-logs
```

#### **Gestionar API Keys**
```bash
# Listar todas las API keys
python manage.py manage_api_keys list

# Listar solo keys activas
python manage.py manage_api_keys list --active-only

# Ver detalles de una API key
python manage.py manage_api_keys show "Mi API Key"

# Desactivar API key
python manage.py manage_api_keys deactivate "Mi API Key"

# Activar API key
python manage.py manage_api_keys activate "Mi API Key"

# Eliminar API key
python manage.py manage_api_keys delete "Mi API Key"
```

### 🛡️ Uso de API Keys

#### **Header Authorization (Recomendado)**
```bash
curl -X POST http://localhost:8000/api/ingest/ \
  -H "Authorization: Bearer tu_api_key_aqui" \
  -H "Content-Type: application/json" \
  -d '{"table": "hired_employees", "records": [...]}'
```

#### **Header X-API-Key (Alternativo)**
```bash
curl -X POST http://localhost:8000/api/ingest/ \
  -H "X-API-Key: tu_api_key_aqui" \
  -H "Content-Type: application/json" \
  -d '{"table": "hired_employees", "records": [...]}'
```

### 🔒 Permisos por Endpoint

| Endpoint | Permiso Requerido | Descripción |
|----------|------------------|-------------|
| `POST /api/ingest/` | `can_ingest` | Ingresar datos a Kafka |
| `POST /api/backup/{table}/` | `can_backup` | Crear backups Parquet |
| `POST /api/restore/{table}/` | `can_restore` | Restaurar desde backups |
| `GET /api/migration-logs/` | `can_view_logs` | Ver logs de migración |
| `GET /api/security-logs/` | `can_view_logs` | Ver logs de seguridad |
| `POST /api/trigger-migration/` | `can_trigger_migration` | Disparar migraciones |
| `GET /api/health/` | Ninguno | Health check (público) |

### ⚡ Rate Limiting

- **Límite por defecto**: 60 requests por minuto por API key
- **Configuración**: Se puede ajustar por endpoint
- **Almacenamiento**: Cache en memoria (se resetea al reiniciar)
- **Logging**: Se registran intentos de exceder el límite

### 🔍 Monitoreo de Seguridad

#### **Panel de Administración Web**
Accede a `http://localhost:8000/admin/` para:

- **📊 Dashboard**: Resumen de API keys, logs y actividad
- **🔑 API Keys**: Crear, editar, activar/desactivar API keys
- **📋 Security Logs**: Ver todos los eventos de seguridad
- **📈 Rate Limits**: Monitorear límites de velocidad
- **📝 Migration Logs**: Ver logs de migración de datos

#### **Ver Logs de Seguridad via API**
```bash
# Ver todos los logs de seguridad
curl -H "Authorization: Bearer tu_api_key" \
  http://localhost:8000/api/security-logs/

# Filtrar por tipo de evento
curl -H "Authorization: Bearer tu_api_key" \
  "http://localhost:8000/api/security-logs/?event_type=AUTH_FAILED"

# Limitar resultados
curl -H "Authorization: Bearer tu_api_key" \
  "http://localhost:8000/api/security-logs/?limit=50"
```

#### **Tipos de Eventos Registrados**
- `AUTH_SUCCESS`: Autenticación exitosa
- `AUTH_FAILED`: Autenticación fallida
- `AUTH_MISSING`: API key faltante
- `AUTH_INVALID`: API key inválida
- `AUTH_EXPIRED`: API key expirada
- `RATE_LIMIT`: Rate limit excedido
- `INVALID_INPUT`: Input inválido
- `UNAUTHORIZED_ACCESS`: Acceso no autorizado

### 🛡️ Protecciones Implementadas

#### **Validación de Entrada**
- ✅ Sanitización de JSON
- ✅ Validación de tamaño de payload (máx. 1MB)
- ✅ Remoción de scripts maliciosos
- ✅ Validación de caracteres de control
- ✅ Límite de longitud por string (10KB)

#### **Headers de Seguridad**
- ✅ `X-Content-Type-Options: nosniff`
- ✅ `X-Frame-Options: DENY`
- ✅ `X-XSS-Protection: 1; mode=block`
- ✅ `Referrer-Policy: strict-origin-when-cross-origin`
- ✅ `Content-Security-Policy: default-src 'self'`

#### **Detección de Amenazas**
- ✅ User-Agents sospechosos (sqlmap, nmap, etc.)
- ✅ Headers de proxy maliciosos
- ✅ Requests de tamaño excesivo
- ✅ JSON malformado

### 🖥️ Panel de Administración Web (Recomendado)

#### **1. Crear Superusuario**
```bash
# Acceder al contenedor
docker-compose exec web bash

# Crear superusuario
python manage.py create_admin_user
# Te pedirá: username, email, password

# O con parámetros específicos
python manage.py create_admin_user --username admin --email admin@example.com
```

#### **2. Acceder al Panel de Administración**
```bash
# Abrir navegador
http://localhost:8000/admin/

# Login con las credenciales del superusuario
```

#### **3. Crear API Keys desde la Web**
- Ir a "API Keys" en el admin
- Click "Add API Key"
- Llenar formulario con permisos
- Guardar → Se muestra la API key

#### **4. Inicialización Rápida**
```bash
# Crear superusuario y API keys por defecto
python manage.py create_admin_user
python manage.py init_security --create-default-keys
```

### 📊 Gestión por Comandos (Alternativo)

```bash
# 1. Crear API key para aplicación de producción
python manage.py manage_api_keys create "Production App" \
  --can-ingest \
  --can-backup \
  --can-restore \
  --can-view-logs \
  --expires-days 365

# 2. Crear API key para administrador
python manage.py manage_api_keys create "Admin User" \
  --can-ingest \
  --can-backup \
  --can-restore \
  --can-view-logs \
  --can-trigger-migration \
  --expires-days 90

# 3. Verificar configuración
python manage.py manage_api_keys list --active-only
```

### 🚨 Respuestas de Error de Seguridad

```json
// API key faltante
{
  "detail": "Authentication credentials were not provided."
}

// API key inválida
{
  "detail": "Invalid API key"
}

// Sin permisos
{
  "detail": "You do not have permission to perform this action."
}

// Rate limit excedido
{
  "detail": "Rate limit exceeded"
}

// Input inválido
{
  "error": "Invalid JSON",
  "message": "Request body contains invalid JSON"
}
```

## Validación de Datos y Logging

### 🔍 Sistema de Validación Robusta

El sistema implementa validaciones exhaustivas que **registran en logs** las transacciones que no cumplen las reglas, **sin insertarlas** en la base de datos.

#### **Reglas de Validación por Tabla**

**Hired Employees:**
- ✅ Campos requeridos: `name`, `datetime`, `department_id`, `job_id`
- ✅ `id` opcional (autoincremental si no se proporciona)
- ✅ `name`: 2-255 caracteres, solo letras y espacios
- ✅ `datetime`: Formato ISO-8601, no puede ser futura
- ✅ `department_id` y `job_id`: Enteros positivos, deben existir en BD
- ✅ `id`: Rango 1-2147483647, no puede duplicarse

**Departments:**
- ✅ Campos requeridos: `id`, `name`
- ✅ `name`: 2-255 caracteres, solo letras y espacios
- ✅ `id`: Entero positivo, no puede duplicarse

**Jobs:**
- ✅ Campos requeridos: `id`, `name`
- ✅ `name`: 2-255 caracteres, solo letras y espacios
- ✅ `id`: Entero positivo, no puede duplicarse

#### **Tipos de Errores Registrados**
- `MISSING_REQUIRED_FIELDS`: Campos obligatorios faltantes
- `VALIDATION_ERROR`: Datos no cumplen reglas de formato
- `BATCH_SUMMARY`: Resumen de procesamiento de lotes

### 📊 Monitoreo de Validaciones

#### **Ver Logs de Validación**
```bash
# Ver logs de las últimas 24 horas
python manage.py view_validation_logs

# Filtrar por tabla
python manage.py view_validation_logs --table hired_employees

# Ver resumen estadístico
python manage.py view_validation_logs --summary

# Filtrar por tipo de error
python manage.py view_validation_logs --error-type VALIDATION_ERROR
```

#### **Panel de Administración**
Accede a `http://localhost:8000/admin/data_migration/datamigrationlog/` para:
- Ver todos los logs de validación
- Filtrar por tabla, tipo de error, fecha
- Ver datos raw de registros fallidos
- Exportar logs para análisis

### 🔄 Funcionamiento en Migración vs Ingesta

#### **Migración Inicial (CSV → PostgreSQL)**
1. **Lee CSV** en lotes de 1000 registros
2. **Valida cada registro** contra reglas de calidad
3. **Loggea registros fallidos** en `DataMigrationLog`
4. **Inserta solo registros válidos** en PostgreSQL
5. **Reporta estadísticas** de validación

#### **Ingesta en Tiempo Real (API → Kafka → PostgreSQL)**
1. **API valida** registros antes de enviar a Kafka
2. **Loggea registros fallidos** inmediatamente
3. **Solo envía registros válidos** a Kafka
4. **Consumer valida nuevamente** antes de insertar
5. **Doble validación** garantiza calidad de datos

### 📈 Ejemplo de Logs de Validación

```json
{
  "timestamp": "2025-10-08T10:30:00Z",
  "table_name": "hired_employees",
  "record_id": "12345",
  "error_type": "VALIDATION_ERROR",
  "error_message": "department_id 999 no existe en la base de datos",
  "raw_data": {
    "id": 12345,
    "name": "John Doe",
    "datetime": "2023-01-01T10:00:00",
    "department_id": 999,
    "job_id": 1
  }
}
```

### 🎯 Beneficios del Sistema

- ✅ **Calidad de Datos**: Solo datos válidos llegan a la BD
- ✅ **Trazabilidad**: Todos los errores quedan registrados
- ✅ **Auditoría**: Historial completo de validaciones
- ✅ **Debugging**: Datos raw de registros fallidos
- ✅ **Métricas**: Estadísticas de calidad por tabla
- ✅ **Consistencia**: Mismas reglas en migración e ingesta

## 📊 Métricas para PowerBI

### 🎯 Endpoints de Métricas

El sistema incluye endpoints específicos optimizados para integración con PowerBI:

#### **1. Empleados por Trimestre**
```
# Todos los años (recomendado para PowerBI)
GET /api/metrics/employees-by-quarter/

# Año específico (opcional)
GET /api/metrics/employees-by-quarter/?year=2021
```

**Descripción**: Cantidad de empleados contratados por cargo y departamento, divididos por trimestre. Incluye todos los años si no se especifica filtro.

**Respuesta**:
```json
{
  "filtered_year": null,
  "data": [
    {
      "year": 2021,
      "department": "Staff",
      "job": "Recruiter", 
      "q1": 3,
      "q2": 0,
      "q3": 7,
      "q4": 11
    }
  ],
  "total_records": 1
}
```

#### **2. Departamentos Arriba del Promedio**
```
# Todos los años (recomendado para PowerBI)
GET /api/metrics/departments-above-average/

# Año específico (opcional)
GET /api/metrics/departments-above-average/?year=2021
```

**Descripción**: Departamentos que contratan más empleados que el promedio por año. Incluye todos los años si no se especifica filtro.

**Respuesta**:
```json
{
  "filtered_year": null,
  "data": [
    {
      "year": 2021,
      "id": 1,
      "department": "Staff",
      "hired": 12,
      "avg_hires": 8.5
    }
  ],
  "total_records": 1
}
```

### 🔧 Características para PowerBI

- ✅ **Sin autenticación**: Endpoints públicos para fácil acceso
- ✅ **Consultas SQL optimizadas**: Mejor performance con raw SQL
- ✅ **Formato JSON estructurado**: Fácil parsing en PowerBI
- ✅ **Parámetros flexibles**: Año configurable
- ✅ **Metadatos incluidos**: Información adicional para contexto
- ✅ **Ordenamiento pre-configurado**: Datos listos para visualización

### 📈 Uso en PowerBI

1. **Conectar**: Obtener datos → Web → `http://localhost:8000/api/metrics/`
2. **Configurar**: Seleccionar endpoint y parámetros
3. **Transformar**: Expandir columna `data` y crear visualizaciones
4. **Visualizar**: Tablas, gráficos de barras, heatmaps, etc.

### 🧪 Probar Métricas

```bash
# Probar endpoints directamente (todos los años)
curl "http://localhost:8000/api/metrics/employees-by-quarter/"
curl "http://localhost:8000/api/metrics/departments-above-average/"

# Probar con año específico (opcional)
curl "http://localhost:8000/api/metrics/employees-by-quarter/?year=2021"
curl "http://localhost:8000/api/metrics/departments-above-average/?year=2021"
```
