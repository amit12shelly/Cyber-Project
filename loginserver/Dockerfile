FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

COPY . /loginserver

WORKDIR /loginserver

EXPOSE 8820

RUN pip install aioquic
RUN pip install psutil
RUN pip install bcrypt
RUN pip install SQLAlchemy

CMD ["python", "login_server.py"]