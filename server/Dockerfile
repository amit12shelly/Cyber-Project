FROM python:3.13-slim

COPY . /server

WORKDIR /server

EXPOSE 4433/udp

RUN pip install pygame aioquic


CMD ["python", "main.py"]