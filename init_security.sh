#!/bin/bash

# Script para inicializar el sistema de seguridad
# Ejecutar dentro del contenedor web

echo "🔐 Inicializando sistema de seguridad..."

# Verificar si Django está funcionando
echo "📋 Verificando Django..."
python manage.py check

# Crear migraciones si es necesario
echo "📦 Creando migraciones..."
python manage.py makemigrations data_migration

# Aplicar migraciones
echo "🗄️ Aplicando migraciones..."
python manage.py migrate

# Crear superusuario si no existe
echo "👑 Verificando superusuario..."
if ! python manage.py shell -c "from django.contrib.auth.models import User; print('Superuser exists:', User.objects.filter(is_superuser=True).exists())" | grep -q "True"; then
    echo "🔑 Creando superusuario..."
    python manage.py create_admin_user
else
    echo "✅ Superusuario ya existe"
fi

# Inicializar API keys por defecto
echo "🔑 Creando API keys por defecto..."
python manage.py init_security --create-default-keys

echo ""
echo "🎉 ¡Sistema de seguridad inicializado!"
echo ""
echo "🌐 Accede al panel de administración:"
echo "   http://localhost:8000/admin/"
echo ""
echo "📚 Para más información, consulta el README.md"
