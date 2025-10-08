from rest_framework import serializers
from .models import HiredEmployee, Department, Job, DataMigrationLog


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name']


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ['id', 'name']


class HiredEmployeeSerializer(serializers.ModelSerializer):
    department_id = serializers.IntegerField(write_only=True)
    job_id = serializers.IntegerField(write_only=True)
    department = DepartmentSerializer(read_only=True)
    job = JobSerializer(read_only=True)
    
    class Meta:
        model = HiredEmployee
        fields = ['id', 'name', 'datetime', 'department_id', 'job_id', 'department', 'job']
    
    def validate(self, data):
        # Validar que department_id existe
        if 'department_id' in data:
            try:
                Department.objects.get(id=data['department_id'])
            except Department.DoesNotExist:
                raise serializers.ValidationError({
                    'department_id': 'Department with this ID does not exist'
                })
        
        # Validar que job_id existe
        if 'job_id' in data:
            try:
                Job.objects.get(id=data['job_id'])
            except Job.DoesNotExist:
                raise serializers.ValidationError({
                    'job_id': 'Job with this ID does not exist'
                })
        
        return data


class BatchTransactionSerializer(serializers.Serializer):
    """Serializer para lotes de transacciones"""
    table_name = serializers.ChoiceField(choices=['hired_employees', 'departments', 'jobs'])
    records = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=1000
    )
    
    def validate_records(self, value):
        if not value:
            raise serializers.ValidationError("Records list cannot be empty")
        return value


class MigrationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataMigrationLog
        fields = ['timestamp', 'table_name', 'record_id', 'error_type', 'error_message', 'raw_data']
