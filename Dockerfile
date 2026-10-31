FROM mcr.microsoft.com/playwright/python:v1.64.1-jammy

WORKDIR /app

# Install python libraries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY . .

# Run FastAPI using Render's dynamic PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]