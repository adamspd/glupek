FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py translator.py database.py ./

# Create directories
RUN mkdir -p /app/logs /app/data && chmod 777 /app/logs /app/data

CMD ["python", "-u", "bot.py"]
