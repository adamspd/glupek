FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY bot.py translator.py ./

# Create logs directory with proper permissions
RUN mkdir -p /app/logs && chmod 777 /app/logs

# Run as non-root user
RUN useradd -m -u 1000 glupek && chown -R glupek:glupek /app
USER glupek

CMD ["python", "-u", "bot.py"]
