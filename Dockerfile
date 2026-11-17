# 앱 이미지: API, 워커, 생성기가 같은 이미지를 쓰고 실행 명령만 다릅니다.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY data/telemetry ./data/telemetry
ENV PYTHONPATH=/app/src
RUN useradd -m app
USER app
EXPOSE 8000 9100
CMD ["uvicorn", "soc.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
