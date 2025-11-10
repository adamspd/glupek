FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY bot.py translator.py ./

# Create logs directory
RUN mkdir -p /app/logs

CMD ["python", "-u", "bot.py"]
