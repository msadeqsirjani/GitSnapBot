FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gitsnapbot ./gitsnapbot

ENV DATA_DIR=/app/data
VOLUME ["/app/data"]

CMD ["python", "-m", "gitsnapbot"]
