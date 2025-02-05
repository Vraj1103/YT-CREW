# Dockerfile.app

# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy only requirements to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port on which FastAPI will run
EXPOSE 8000

# Default command (will be overridden for the worker)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
