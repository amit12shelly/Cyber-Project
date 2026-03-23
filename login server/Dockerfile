FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

COPY . /login server/

WORKDIR /login server

EXPOSE 8820

RUN pip install aioquic
RUN pip install psutil


CMD ["python", "login_server.py"]