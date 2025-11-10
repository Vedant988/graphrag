#!/bin/bash

if ! which curl >/dev/null; then
  echo "cURL is not found, please install it and retry."
  exit 1
fi

if ! docker compose >/dev/null; then
  echo "Docker Compose plugin is not working properly, please resolve it and retry."
  echo "Refer to https://docs.docker.com/compose/install/linux/ for more installation instructions."
  exit 2
fi

root_dir=${1:-./graphrag}
tg_host=${2:-http://tigergraph}
tg_port=${3:-14240}
tg_username=$(echo ${4:-tigergraph} | sed 's/[][\/.^$*+?|(){}]/\\&/g')
tg_password=$(echo ${5:-tigergraph} | sed 's/[][\/.^$*+?|(){}]/\\&/g')

if [[ -z $OPENAI_API_KEY ]]; then
  echo "OPENAI_API_KEY is not found in current environment, please set it using 'export OPENAI_API_KEY=xxx'."
  exit 5
fi

if ! [[ "$tg_host" =~ ^http[s]?:// ]]; then
  if [[ "$tg_port" == "443" ]]; then
    tg_host="https://${tg_host}"
  else
    tg_host="http://${tg_host}"
  fi
  echo "Rewriting tg_host to ${tg_host} based on tg_port: ${tg_port}"
fi

if ! [[ "$tg_host" =~ ^http[s]?://tigergraph ]]; then
  pong=$(curl -s ${tg_host}:${tg_port}/api/ping)
  if ! echo $pong | grep "pong" >/dev/null; then
    echo "Cannot connect to TigerGraph instance at ${tg_host}:${tg_port}"
    exit 3
  fi
fi

mkdir -p $root_dir || true
[[ -d $root_dir ]] || (echo "Target dir $root_dir is not found!" && exit 6)

echo "Entering GraphRAG root dir: $root_dir"
cd $root_dir || (echo "Cannot switch to $root_dir!" && exit 6)

echo "Downloading GraphRAG sevice config..."
mkdir -p configs || true
curl -sk https://raw.githubusercontent.com/tigergraph/graphrag/refs/heads/main/docs/tutorials/docker-compose-tg.yml | sed "s/community:4.2.1/community:${tg_version}/g" > docker-compose.yml
curl -sk https://raw.githubusercontent.com/tigergraph/graphrag/refs/heads/main/docs/tutorials/configs/nginx.conf -o configs/nginx.conf
curl -sk https://raw.githubusercontent.com/tigergraph/graphrag/refs/heads/main/docs/tutorials/configs/server_config.json | sed '/"gsPort": "14240"/a\
    "username": "'${tg_username}'",\
    "password": "'${tg_password}'",
' | sed "s#http://tigergraph#${tg_host}#g; s/14240/${tg_port}/g" | sed "s/YOUR_OPENAI_API_KEY_HERE/${OPENAI_API_KEY}/g"> configs/server_config.json

exit
echo "Starting GraphRAG sevices.."
docker compose pull --ignore-pull-failures
docker compose up -d
sleep 5

echo "Checking service status..."
if ! curl -s http://localhost:14240/restpp/version >/dev/null; then
  docker exec tigergraph /home/tigergraph/tigergraph/app/cmd/gadmin start all >/dev/null
  docker compose up -d >/dev/null
  sleep 5
fi

if ! docker ps | grep "tigergraph/graphrag:latest" >/dev/null; then
  echo "Failed to start GraphRAG service."
  echo 'Please double check tigergraph username and password in configs/server_config.json, and re-run `docker compose up -d`'
  echo 'Or check log via `docker logs graphrag` for detailed failure.'
else
  echo "GraphRAG service started successfully."
  echo "Visit http://localhost to access the chatbot."
fi
cd - >/dev/null

