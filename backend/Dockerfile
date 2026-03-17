FROM python:3.12-slim

# Set working directory inside container
WORKDIR /app

# Install dependencies first (Docker caches this layer — rebuilds are faster)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Default command (overridden by docker-compose for celery services)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]