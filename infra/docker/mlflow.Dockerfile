FROM python:3.12-slim
RUN pip install --no-cache-dir mlflow==3.14.0 "psycopg[binary]>=3.2,<4" "boto3>=1.35,<2"
EXPOSE 5000
ENTRYPOINT ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000"]
