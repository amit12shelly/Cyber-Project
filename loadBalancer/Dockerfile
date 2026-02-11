FROM python:3.13-slim

COPY . /loadBalncer

WORKDIR /loadBalncer

EXPOSE 4433

RUN pip install aioquic


CMD ["python", "main.py"]