
# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . /app

EXPOSE 8501

# Environment (bind via docker-compose or cloud)
# ENV SUPABASE_URL= ...
# ENV SUPABASE_ANON_KEY= ...

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
