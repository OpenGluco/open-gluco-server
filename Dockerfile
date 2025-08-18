FROM python:3

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 1 worker for now, logging must be changed in order to avoid duplicate logging
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8000", "main:app"]