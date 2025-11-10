# Copyright (c) 2025 TigerGraph, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import boto3, botocore
from langchain_aws import ChatBedrock
import logging
from common.llm_services import LLM_Model
from common.logs.log import req_id_cv
from common.logs.logwriter import LogWriter

logger = logging.getLogger(__name__)


class AWSBedrock(LLM_Model):
    def __init__(self, config):
        super().__init__(config)
        model_name = config["llm_model"]

        boto3_config = config.get("boto3_config", {})
        client_config = botocore.config.Config(
            max_pool_connections=boto3_config.get("max_pool_connections", 20),
            read_timeout=boto3_config.get("read_timeout", 300),
            retries={"max_attempts": boto3_config.get("retries", 5)},
        )

        client = boto3.client(
            "bedrock-runtime",
            region_name=config.get("region_name", "us-east-1"),
            config=client_config,
            aws_access_key_id=config["authentication_configuration"][
                "AWS_ACCESS_KEY_ID"
            ],
            aws_secret_access_key=config["authentication_configuration"][
                "AWS_SECRET_ACCESS_KEY"
            ],
        )
        self.llm = ChatBedrock(
            client=client,
            model_id=model_name,
            region_name=config.get("region_name", "us-east-1"),
            model_kwargs=config.get("model_kwargs", {"temperature": 0}),
        )

        self.prompt_path = config["prompt_path"]
        LogWriter.info(
            f"request_id={req_id_cv.get()} instantiated AWSBedrock model_name={model_name}"
        )

    @property
    def map_question_schema_prompt(self):
        return self._read_prompt_file(self.prompt_path + "map_question_to_schema.txt")

    @property
    def generate_function_prompt(self):
        return self._read_prompt_file(self.prompt_path + "generate_function.txt")

    @property
    def entity_relationship_extraction_prompt(self):
        return self._read_prompt_file(
            self.prompt_path + "entity_relationship_extraction.txt"
        )

    @property
    def generate_cypher_prompt(self):
        filepath = self.prompt_path + "generate_cypher.txt"
        if os.path.exists(filepath):
            return self._read_prompt_file(filepath)
        else:
            return super().generate_cypher_prompt

    @property
    def generate_gsql_prompt(self):
        filepath = self.prompt_path + "generate_gsql.txt"
        if os.path.exists(filepath):
            return self._read_prompt_file(filepath)
        else:
            return super().generate_gsql_prompt

    @property
    def chatbot_response_prompt(self):
        filepath = self.prompt_path + "chatbot_response.txt"
        if os.path.exists(filepath):
            return self._read_prompt_file(filepath)
        else:
            return super().chatbot_response_prompt

    @property
    def graphrag_scoring_prompt(self):
        filepath = self.prompt_path + "graphrag_scoring.txt"
        if os.path.exists(filepath):
            return self._read_prompt_file(filepath)
        else:
            return super().graphrag_scoring_prompt

    @property
    def model(self):
        return self.llm
