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

import logging
from typing import Iterable
from langchain_community.callbacks.manager import get_openai_callback
from langchain_core.output_parsers import StrOutputParser
from langchain.prompts import PromptTemplate
from langchain.tools import BaseTool
from langchain.llms.base import LLM
from common.metrics.tg_proxy import TigerGraphConnectionProxy
from common.db.connections import get_schema_ver
from common.db.schema_utils import generate_schema_rep

logger = logging.getLogger(__name__)


class GenerateGSQL(BaseTool):
    """GenerateGSQL Tool.
    Tool to generate and execute the appropriate GSQL query for the question.
    """
    name: str = "GenerateGSQL"
    description: str = "Generates a GSQL query for the question."
    conn: TigerGraphConnectionProxy = None
    llm: LLM = None
    schema_rep: str = None
    schema_ver: int = 0

    def __init__(self, conn: TigerGraphConnectionProxy, llm):
        """Initialize GenerateGSQL.
        Args:
            conn (TigerGraphConnection):
                pyTigerGraph TigerGraphConnection connection to the appropriate database/graph with correct permissions
            llm (LLM_Model):
                LLM_Model class to interact with an external LLM API.
            prompt (str):
                prompt to use with the LLM_Model. Varies depending on LLM service.
        """
        super().__init__()
        self.conn = conn
        self.llm = llm
        self.schema_rep = ""
        self.schema_ver = 0
    
    def _generate_schema_rep(self):
        self.schema_rep, self.schema_ver = generate_schema_rep(self.conn, self.schema_rep, self.schema_ver)
        return self.schema_rep
        
    def generate_gsql(self, question: str, history: Iterable[str]) -> str:
        """Generate GSQL query for the question.
        Args:
            question (str):
                question to generate the GSQL query for.
            history (Iterable[str]):
                conversation history for context.
        Returns:
            str:
                GSQL query for the question.
        """
        PROMPT = PromptTemplate(
            template=self.llm.generate_gsql_prompt,
            input_variables=[
                "question",
                "schema",
                "history"
            ]
        )

        schema = self._generate_schema_rep()
    
        logger.debug_pii("Prompt to LLM:\n" + PROMPT.invoke({"question": question, "schema": schema, "history": history}).to_string())

        chain = PROMPT | self.llm.model | StrOutputParser()
        usage_data = {}
        with get_openai_callback() as cb:
            out = chain.invoke({"question": question, "schema": schema, "history": history}).strip("```gsql").strip("```")

            usage_data["input_tokens"] = cb.prompt_tokens
            usage_data["output_tokens"] = cb.completion_tokens
            usage_data["total_tokens"] = cb.total_tokens
            usage_data["cost"] = cb.total_cost
            logger.info(f"generate_gsql usage: {usage_data}")

        query_header = "USE GRAPH " + self.conn.graphname + " "+ "\n" + "INTERPRET QUERY () FOR GRAPH " + self.conn.graphname + " {" + "\n"
        query_footer = "\n}"
        return query_header + out + query_footer
    
    def _run(self, question: str, history: Iterable[str]):
        """Run the GenerateGSQL tool.
        Args:
            question (str):
                question to generate the GSQL query for.
            history (Iterable[str]):
                conversation history for context.
        Returns:
            str:
                GSQL query for the question.
        """
        return self.generate_gsql(question, history)
    
    def _arun(self, question: str, history: Iterable[str]):
        raise NotImplementedError("Asynchronous execution is not supported for this tool.") 