FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

COPY . /loginserver

WORKDIR /loginserver

EXPOSE 4433

RUN pip install aioquic


CMD ["python", "login_server.py"]