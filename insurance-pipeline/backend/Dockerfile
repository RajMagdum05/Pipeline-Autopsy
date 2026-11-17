FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY database ./database
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
