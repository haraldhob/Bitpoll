FROM httpd:latest

RUN apt-get update && \
    apt-get install apache2-dev wget -y && \
    wget https://raw.githubusercontent.com/unbit/uwsgi/master/apache2/mod_proxy_uwsgi.c && \
    apxs -ci mod_proxy_uwsgi.c

COPY ./docker_testing/apache/httpd.conf /usr/local/apache2/conf/httpd.conf
COPY ./ /app/