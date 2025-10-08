import logging
import signal
import sys
import time
from collections import defaultdict

import pandas as pd
from django.core.management.base import BaseCommand
from django.conf import settings

from confluent_kafka import DeserializingConsumer
from confluent_kafka.serialization import StringDeserializer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONDeserializer

from data_migration.services import DataMigrationService
from data_migration.validators import validate_and_log_record, DataQualityLogger


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run Kafka consumer to read raw.* topics, validate, and load into PostgreSQL in batches of 1000'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', type=str, default='ingest-consumer-group')
        parser.add_argument('--poll-ms', type=int, default=500)
        parser.add_argument('--batch-size', type=int, default=1000)

    def handle(self, *args, **options):
        group_id = options['group_id']
        poll_ms = options['poll_ms']
        batch_size = options['batch_size']

        # JSON Schema for the envelope produced by /ingest
        envelope_schema_str = (
            '{"title":"IngestEnvelope","type":"object","additionalProperties":false,'
            '"properties":{'
            '  "table":{"type":"string"},'
            '  "payload":{"type":"object"}'
            '},"required":["table","payload"]}'
        )
        json_deserializer = JSONDeserializer(envelope_schema_str, from_dict=lambda d, ctx: d)

        consumer_conf = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'key.deserializer': StringDeserializer('utf_8'),
            'value.deserializer': json_deserializer,
            'group.id': group_id,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
        }

        consumer = DeserializingConsumer(consumer_conf)
        topics = ['raw.hired_employees', 'raw.departments', 'raw.jobs']
        consumer.subscribe(topics)
        logger.info(f"Kafka consumer subscribed to: {topics}")

        buffers = defaultdict(list)  # table -> list of payloads
        last_flush = defaultdict(lambda: time.monotonic())  # table -> last flush time
        svc = DataMigrationService()
        running = True

        def _flush(table: str):
            items = buffers[table]
            if not items:
                return
            try:
                df = pd.DataFrame(items)
                # Reuse load path; this does TRUNCATE in full loader, so call lower-level batch loader
                # Here we call the COPY loader directly per table without truncate
                if table == 'hired_employees':
                    # separar con id y sin id
                    with_id = df[df['id'].notna()] if 'id' in df.columns else pd.DataFrame(columns=df.columns)
                    without_id = df[df['id'].isna()] if 'id' in df.columns else df

                    # flush con id
                    if not with_id.empty:
                        tmp = with_id.copy()
                        if 'datetime' in tmp.columns:
                            tmp['datetime'] = pd.to_datetime(tmp['datetime'], errors='coerce')
                            tmp = tmp.dropna(subset=['datetime'])
                        for col in ['id', 'department_id', 'job_id']:
                            if col in tmp.columns:
                                tmp[col] = pd.to_numeric(tmp[col], errors='coerce')
                        tmp = tmp.dropna(subset=['id', 'department_id', 'job_id'])
                        tmp[['id','department_id','job_id']] = tmp[['id','department_id','job_id']].astype('int64')
                        svc._load_with_copy(tmp[['id','name','datetime','department_id','job_id']], 'hired_employees')

                    # flush sin id (autoincrement)
                    if not without_id.empty:
                        tmp2 = without_id.copy()
                        svc._load_with_copy_no_id(tmp2[['name','datetime','department_id','job_id']], 'hired_employees')
                elif table == 'departments':
                    tmp = df.copy()
                    tmp['id'] = pd.to_numeric(tmp['id'], errors='coerce')
                    tmp = tmp.dropna(subset=['id','name'])
                    tmp['id'] = tmp['id'].astype('int64')
                    logger.info(f"Flushing departments rows: {len(tmp)}")
                    svc._load_with_copy(tmp[['id','name']], 'departments')
                elif table == 'jobs':
                    tmp = df.copy()
                    tmp['id'] = pd.to_numeric(tmp['id'], errors='coerce')
                    tmp = tmp.dropna(subset=['id','name'])
                    tmp['id'] = tmp['id'].astype('int64')
                    logger.info(f"Flushing jobs rows: {len(tmp)}")
                    svc._load_with_copy(tmp[['id','name']], 'jobs')
                logger.info(f"Flushed {len(items)} records to {table}")
                buffers[table].clear()
                last_flush[table] = time.monotonic()
            except Exception as e:
                logger.error(f"Error flushing to {table}: {e}")
                # evitar reintentos infinitos con el mismo lote
                buffers[table].clear()
                last_flush[table] = time.monotonic()

        def shutdown(signum, frame):
            nonlocal running
            running = False
            logger.info("Shutdown signal received, flushing buffers...")
            for tbl in list(buffers.keys()):
                _flush(tbl)
            consumer.close()

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        required_fields = {
            # id es opcional en hired_employees (auto-increment)
            'hired_employees': ['name', 'datetime', 'department_id', 'job_id'],
            'departments': ['id', 'name'],
            'jobs': ['id', 'name']
        }

        while running:
            try:
                msg = consumer.poll(poll_ms / 1000.0)
                if msg is None:
                    # time-based flush for any table with pending records
                    now = time.monotonic()
                    for tbl in list(buffers.keys()):
                        if buffers[tbl] and (now - last_flush[tbl] >= 2.0):
                            _flush(tbl)
                    continue
                if msg.error():
                    logger.error(f"Kafka error: {msg.error()}")
                    continue

                value = msg.value()
                if not isinstance(value, dict) or 'table' not in value or 'payload' not in value:
                    logger.warning("Skipping message with invalid envelope")
                    continue

                table = value['table']
                payload = value['payload']
                if table not in required_fields:
                    logger.warning(f"Skipping unknown table {table}")
                    continue

                # Validación robusta usando el sistema de validadores
                if validate_and_log_record(table, payload, len(buffers[table])):
                    buffers[table].append(payload)
                else:
                    logger.warning(f"Rejected from consumer: table={table} validation failed")
                    continue
                # flush on size threshold or after short wait to handle small volumes
                if len(buffers[table]) >= batch_size or (time.monotonic() - last_flush[table] >= 2.0):
                    _flush(table)

            except Exception as e:
                logger.error(f"Consumer loop error: {e}")
                time.sleep(1)

        # Final flush handled in shutdown
        logger.info("Consumer stopped")


