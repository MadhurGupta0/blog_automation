FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY blogautomation.py .
COPY seotrends.py .

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# All secrets come from ECS task definition env vars — no .env file baked in
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
