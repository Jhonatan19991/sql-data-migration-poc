FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create .dlt directory if it doesn't exist
RUN mkdir -p .dlt

# Create data directory
RUN mkdir -p /app/data

# Create logs directory
RUN mkdir -p /app/logs

# Run migrations and start server
CMD ["sh", "-c", "python manage.py migrate && python manage.py run_migration && python manage.py runserver 0.0.0.0:8000"]
