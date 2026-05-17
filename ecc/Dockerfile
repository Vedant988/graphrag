FROM python:3.11.9-bullseye
WORKDIR /code

ARG PYTHON_REQUIREMENTS=common/requirements.cloud.txt
COPY ${PYTHON_REQUIREMENTS} requirements.txt
 
RUN apt-get update && apt-get upgrade -y
RUN pip install -r requirements.txt

COPY ecc/app /code
RUN rm -f /code/common /code/configs
COPY common /code/common
COPY configs/server_config.json /server_config.json

ENV SERVER_CONFIG="/server_config.json"
ENV LOGLEVEL="INFO"

EXPOSE 8001
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8001}"]
