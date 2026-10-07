FROM python:3.12-slim

WORKDIR /app

# pdfplumber needs no extra system deps; PyMySQL is pure Python
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
ENV MYSQL_HOST=futu-db
ENV MYSQL_PORT=3306
ENV MYSQL_DATABASE=futu
ENV MYSQL_USER=mickylee
ENV MYSQL_PASSWORD=Mn12345678

EXPOSE 8080

CMD ["python", "run_web.py"]
