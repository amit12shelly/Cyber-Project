FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

COPY . /server

WORKDIR /server

EXPOSE 4433

RUN pip install aioquic
RUN pip install psutil


CMD ["python", "main.py"]