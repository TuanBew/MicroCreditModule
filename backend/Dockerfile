FROM python:3.12-slim

WORKDIR /app

# Install system deps needed for psycopg binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy project definition and install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir "."

# Copy application code
COPY . .

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
