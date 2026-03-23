FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

COPY . /server

WORKDIR /server

EXPOSE 4433

RUN pip install aioquic
RUN pip install psutil
RUN pip install pygame

CMD ["python", "generate_certs.py"]
CMD ["python", "server_game.py"]