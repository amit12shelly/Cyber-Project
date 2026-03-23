FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

COPY . /loadBalncer

WORKDIR /loadBalncer

EXPOSE 8080

RUN pip install aioquic


CMD ["python", "load_balancer.py"]