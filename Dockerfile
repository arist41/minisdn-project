# Dockerfile - Fixed for Python 3.8
FROM python:3.8-slim-buster

# Install all dependencies with specific versions to avoid conflicts
RUN pip install --no-cache-dir \
    'setuptools<58.0.0' \
    'urllib3==1.26.15' \
    'requests==2.31.0' \
    'eventlet==0.30.2' \
    'flask==2.3.3' \
    'ryu==4.34'

WORKDIR /app
