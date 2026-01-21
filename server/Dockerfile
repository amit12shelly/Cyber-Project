FROM python:3.13-slim

COPY server /server

WORKDIR /server

EXPOSE 4433

RUN "pip install pygame"
RUN "pip install aioquic"

CMD python main.py