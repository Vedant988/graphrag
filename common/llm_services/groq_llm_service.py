import os
import logging
from common.llm_services import LLM_Model
from common.logs.log import req_id_cv
from common.logs.logwriter import LogWriter

logger = logging.getLogger(__name__)


class Groq(LLM_Model):
    def __init__(self, config):
        super().__init__(config)
        for auth_detail, auth_value in config.get(
            "authentication_configuration", {}
        ).items():
            os.environ[auth_detail] = auth_value
        from langchain_groq import ChatGroq

        model_name = config["llm_model"]
        self.llm = ChatGroq(temperature=0, model_name=model_name)
        self.prompt_path = config["prompt_path"]
        LogWriter.info(
            f"request_id={req_id_cv.get()} instantiated OpenAI model_name={model_name}"
        )
