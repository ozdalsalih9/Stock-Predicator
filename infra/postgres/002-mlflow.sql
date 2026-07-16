SELECT 'CREATE DATABASE mlflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow')\gexec
