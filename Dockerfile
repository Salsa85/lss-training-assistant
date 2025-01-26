FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Install dependencies first (for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ .
COPY credentials/ credentials/

# Set proper permissions
RUN chown -R appuser:appuser /app
USER appuser

# Run the application
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"] 