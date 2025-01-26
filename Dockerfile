FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create credentials directory
RUN mkdir -p /app/credentials

# Copy application code
COPY src/ /app/src/

# Add src to Python path
ENV PYTHONPATH=/app/src

# Run the application
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"] 