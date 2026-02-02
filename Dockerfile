FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY reporting_service/ ./reporting_service/
COPY config/ ./config/

# Set Python path
ENV PYTHONPATH=/app

# Default environment variables
ENV REPORTING_DATABASE__JOURNAL_HOST=localhost
ENV REPORTING_DATABASE__JOURNAL_PORT=5432
ENV REPORTING_DATABASE__TIMESCALE_HOST=localhost
ENV REPORTING_DATABASE__TIMESCALE_PORT=5432
ENV REPORTING_LOG_LEVEL=INFO
ENV REPORTING_DAEMON_INTERVAL=300

# Default command - run analysis in daemon mode
CMD ["python", "-m", "reporting_service.runner", "analyze", "--daemon"]
