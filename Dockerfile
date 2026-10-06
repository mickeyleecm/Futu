FROM python:3.12-slim

WORKDIR /app

# pdfplumber / pypdf need no system deps; psycopg2-binary is self-contained
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY web/ web/
COPY scripts/ scripts/
COPY db/ db/
COPY main.py run_web.py ./
COPY config/config.example.yaml config/config.example.yaml

RUN mkdir -p uploads

ENV FUTU_OPEND_HOST=host.docker.internal
ENV FUTU_OPEND_PORT=11111
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=8080
ENV POSTGRES_HOST=futu-db
ENV POSTGRES_PORT=5432
ENV POSTGRES_DB=futu
ENV POSTGRES_USER=mickylee
ENV POSTGRES_PASSWORD=Mn12345678

EXPOSE 8080

CMD ["python", "run_web.py"]
