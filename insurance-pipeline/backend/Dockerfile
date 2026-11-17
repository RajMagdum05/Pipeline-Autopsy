FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/insurance-pipeline/backend
COPY autopsy-sdk /app/autopsy-sdk
COPY insurance-pipeline/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY insurance-pipeline/backend/app ./app
COPY insurance-pipeline/database ../database
COPY insurance-pipeline/demo_documents ../demo_documents
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
