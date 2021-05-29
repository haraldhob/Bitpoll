# syntax=docker/dockerfile:1
FROM python:3.8

# first, only copy all production requirements
COPY ./requirements.txt /app/requirements.txt
WORKDIR /app

# install all requirements
RUN pip install -r /app/requirements.txt

# copy all required files and start application (uwsgi)
COPY ./ /app/
CMD bash ./start.sh
