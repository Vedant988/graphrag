import logging
import os
import threading
import time
from typing import List

from langchain.schema.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_ollama import OllamaEmbeddings

from common.logs.log import req_id_cv
from common.logs.logwriter import LogWriter
from common.metrics.prometheus_metrics import metrics
from common.utils.gemini_fallback import collect_gemini_api_keys, is_gemini_rate_limit_error
from common.utils.token_calculator import get_token_calculator

logger = logging.getLogger(__name__)


class EmbeddingModel(Embeddings):
    """EmbeddingModel.
    Implements connections to the desired embedding API.
    """

    def __init__(self, config: dict, model_name: str):
        """Initialize an EmbeddingModel
        Read JSON config file and export the details as environment variables.
        """
        if "authentication_configuration" in config:
            for auth_detail in config["authentication_configuration"].keys():
                os.environ[auth_detail] = config["authentication_configuration"][
                    auth_detail
                ]
        self.embeddings = None
        self.model_name = model_name
        self.dimensions = config.get("dimensions", 1536)
        self.token_calculator = get_token_calculator(token_limit=config.get("token_limit", 8192), model_name=model_name)
        LogWriter.info(
            f"request_id={req_id_cv.get()} instantiated AI model_name={model_name} with dimensions={self.dimensions}"
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed Documents.
        Generate embeddings for a list of documents.

        Args:
            texts (List[str]):
                List of documents to embed.
        Returns:
            Nested lists of floats that contain embeddings.
        """
        start_time = time.time()
        metrics.llm_inprogress_requests.labels(self.model_name).inc()

        try:
            LogWriter.info(f"request_id={req_id_cv.get()} ENTRY embed_documents()")

            if not self.token_calculator.is_unlimited_tokens():
                max_context_tokens = self.token_calculator.get_max_context_tokens()
                if any(len(text) > max_context_tokens for text in texts):
                    if any(self.token_calculator.count_tokens(text) > max_context_tokens for text in texts):
                        texts = [self.token_calculator.truncate_to_token_limit(text, max_context_tokens) for text in texts]

            docs = self._embed_documents_impl(texts)
            LogWriter.info(f"request_id={req_id_cv.get()} EXIT embed_documents()")
            metrics.llm_success_response_total.labels(self.model_name).inc()
            return docs
        except Exception as e:
            metrics.llm_query_error_total.labels(self.model_name).inc()
            raise e
        finally:
            metrics.llm_request_total.labels(self.model_name).inc()
            metrics.llm_inprogress_requests.labels(self.model_name).dec()
            duration = time.time() - start_time
            metrics.llm_request_duration_seconds.labels(self.model_name).observe(
                duration
            )

    def embed_query(self, question: str) -> List[float]:
        """Embed Query.
        Embed a string.

        Args:
            question (str):
                A string to embed.
        """
        start_time = time.time()
        metrics.llm_inprogress_requests.labels(self.model_name).inc()

        try:
            LogWriter.info(f"request_id={req_id_cv.get()} ENTRY embed_query()")
            logger.debug_pii(
                f"request_id={req_id_cv.get()} embed_query() embedding question={question}"
            )

            if not self.token_calculator.is_unlimited_tokens():
                max_context_tokens = self.token_calculator.get_max_context_tokens()
                if len(question) > max_context_tokens:
                    if self.token_calculator.count_tokens(question) > max_context_tokens:
                        question = self.token_calculator.truncate_to_token_limit(question, max_context_tokens)

            query_embedding = self._embed_query_impl(question)
            LogWriter.info(f"request_id={req_id_cv.get()} EXIT embed_query()")
            metrics.llm_success_response_total.labels(self.model_name).inc()
            return query_embedding
        except Exception as e:
            metrics.llm_query_error_total.labels(self.model_name).inc()
            raise e
        finally:
            metrics.llm_request_total.labels(self.model_name).inc()
            metrics.llm_inprogress_requests.labels(self.model_name).dec()
            duration = time.time() - start_time
            metrics.llm_request_duration_seconds.labels(self.model_name).observe(
                duration
            )

    async def aembed_query(self, question: str) -> List[float]:
        """Embed Query Async.
        Embed a string.

        Args:
            question (str):
                A string to embed.
        """
        # start_time = time.time()
        # metrics.llm_inprogress_requests.labels(self.model_name).inc()

        # try:
        LogWriter.info(f"request_id={req_id_cv.get()} ENTRY aembed_query()")
        logger.debug_pii(f"aembed_query() embedding question={question}")
        if not self.token_calculator.is_unlimited_tokens():
            max_context_tokens = self.token_calculator.get_max_context_tokens()
            if len(question) > max_context_tokens:
                if self.token_calculator.count_tokens(question) > max_context_tokens:
                    question = self.token_calculator.truncate_to_token_limit(question, max_context_tokens)

        query_embedding = await self._aembed_query_impl(question)
        LogWriter.info(f"request_id={req_id_cv.get()} EXIT aembed_query()")
        # metrics.llm_success_response_total.labels(self.model_name).inc()
        return query_embedding
        # except Exception as e:
        #     # metrics.llm_query_error_total.labels(self.model_name).inc()
        #     raise e
        # finally:
        #     metrics.llm_request_total.labels(self.model_name).inc()
        #     metrics.llm_inprogress_requests.labels(self.model_name).dec()
        #     duration = time.time() - start_time
        #     metrics.llm_request_duration_seconds.labels(self.model_name).observe(
        #         duration
        #     )

    def _embed_documents_impl(self, texts: List[str]) -> List[List[float]]:
        if isinstance(self.embeddings, GoogleGenerativeAIEmbeddings):
            return self.embeddings.embed_documents(
                texts, output_dimensionality=self.dimensions
            )
        return self.embeddings.embed_documents(texts)

    def _embed_query_impl(self, question: str) -> List[float]:
        if isinstance(self.embeddings, GoogleGenerativeAIEmbeddings):
            return self.embeddings.embed_query(
                question, output_dimensionality=self.dimensions
            )
        return self.embeddings.embed_query(question)

    async def _aembed_query_impl(self, question: str) -> List[float]:
        if isinstance(self.embeddings, GoogleGenerativeAIEmbeddings):
            return await self.embeddings.aembed_query(
                question, output_dimensionality=self.dimensions
            )
        return await self.embeddings.aembed_query(question)


class AzureOpenAI_Ada002(EmbeddingModel):
    """Azure OpenAI Ada-002 Embedding Model"""

    def __init__(self, config):
        super().__init__(config, model_name=config.get("model_name", "text-embedding-3-small"))
        from langchain_openai import AzureOpenAIEmbeddings

        self.embeddings = AzureOpenAIEmbeddings(model=self.model_name, dimensions=self.dimensions, deployment=config["azure_deployment"])


class OpenAI_Embedding(EmbeddingModel):
    """OpenAI Embedding Model"""

    def __init__(self, config):
        super().__init__(
            config, model_name=config.get("model_name", "text-embedding-3-small")
        )

        self.embeddings = OpenAIEmbeddings(model=self.model_name, base_url=config.get("base_url"))


class VertexAI_PaLM_Embedding(EmbeddingModel):
    """VertexAI PaLM Embedding Model"""

    def __init__(self, config):
        super().__init__(config, model_name=config.get("model_name", "VertexAI PaLM"))
        from langchain_google_vertexai import VertexAIEmbeddings

        self.embeddings = VertexAIEmbeddings(model=self.model_name)


class GenAI_Embedding(EmbeddingModel):
    """Google GenAI Embedding Model"""

    def __init__(self, config):
        super().__init__(config, model_name=config.get("model_name", "gemini-embedding-exp-03-07"))
        self._client_lock = threading.Lock()
        self._api_keys = collect_gemini_api_keys(config)
        self._embedding_clients: dict[str, GoogleGenerativeAIEmbeddings] = {}
        self._active_api_key_index = 0
        self._active_api_key = self._api_keys[0] if self._api_keys else ""
        self.embeddings = self._client_for_key(self._active_api_key)

    def _build_client(self, api_key: str | None) -> GoogleGenerativeAIEmbeddings:
        kwargs = {"model": self.model_name}
        if api_key:
            kwargs["google_api_key"] = api_key
            os.environ["GOOGLE_API_KEY"] = api_key
        return GoogleGenerativeAIEmbeddings(**kwargs)

    def _client_for_key(self, api_key: str | None) -> GoogleGenerativeAIEmbeddings:
        cache_key = api_key or "__default__"
        client = self._embedding_clients.get(cache_key)
        if client is None:
            client = self._build_client(api_key)
            self._embedding_clients[cache_key] = client
        return client

    def _set_active_key_unlocked(self, index: int) -> None:
        self._active_api_key_index = index
        self._active_api_key = self._api_keys[index] if self._api_keys else ""
        self.embeddings = self._client_for_key(self._active_api_key)

    def _active_client_state(self):
        with self._client_lock:
            return self._active_api_key, self.embeddings

    def _activate_next_key(self, attempted_keys: set[str]) -> bool:
        if len(self._api_keys) <= 1:
            return False
        with self._client_lock:
            for offset in range(1, len(self._api_keys)):
                next_index = (self._active_api_key_index + offset) % len(self._api_keys)
                next_key = self._api_keys[next_index]
                if next_key in attempted_keys:
                    continue
                self._set_active_key_unlocked(next_index)
                return True
        return False

    def _invoke_with_fallback_sync(self, method_name: str, *args, **kwargs):
        attempted_keys: set[str] = set()
        while True:
            api_key, client = self._active_client_state()
            attempted_keys.add(api_key or "__default__")
            try:
                return getattr(client, method_name)(*args, **kwargs)
            except Exception as exc:
                if not is_gemini_rate_limit_error(exc):
                    raise
                if not self._activate_next_key(attempted_keys):
                    raise
                LogWriter.warning(
                    f"{method_name} hit Gemini rate limits on the active embedding key; "
                    "rotating to the next configured fallback key."
                )

    async def _invoke_with_fallback_async(self, method_name: str, *args, **kwargs):
        attempted_keys: set[str] = set()
        while True:
            api_key, client = self._active_client_state()
            attempted_keys.add(api_key or "__default__")
            try:
                return await getattr(client, method_name)(*args, **kwargs)
            except Exception as exc:
                if not is_gemini_rate_limit_error(exc):
                    raise
                if not self._activate_next_key(attempted_keys):
                    raise
                LogWriter.warning(
                    f"{method_name} hit Gemini rate limits on the active embedding key; "
                    "rotating to the next configured fallback key."
                )

    def _embed_documents_impl(self, texts: List[str]) -> List[List[float]]:
        return self._invoke_with_fallback_sync(
            "embed_documents", texts, output_dimensionality=self.dimensions
        )

    def _embed_query_impl(self, question: str) -> List[float]:
        return self._invoke_with_fallback_sync(
            "embed_query", question, output_dimensionality=self.dimensions
        )

    async def _aembed_query_impl(self, question: str) -> List[float]:
        return await self._invoke_with_fallback_async(
            "aembed_query", question, output_dimensionality=self.dimensions
        )


class AWS_Bedrock_Embedding(EmbeddingModel):
    """AWS Bedrock Embedding Model"""

    def __init__(self, config):
        import boto3, botocore
        from langchain_aws import BedrockEmbeddings

        super().__init__(config=config, model_name=config.get("model_name", "amazon.titan-embed-text-v1"))

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
        self.embeddings = BedrockEmbeddings(client=client, model_id=self.model_name)


class Ollama_Embedding(EmbeddingModel):
    """Ollama Embedding Model"""

    def __init__(self, config):
        from langchain_ollama import OllamaEmbeddings

        super().__init__(config=config, model_name=config.get("model_name", "llama3"))

        # Get Ollama configuration from config
        base_url = config.get("base_url", "http://localhost:11434")

        self.embeddings = OllamaEmbeddings(
            model=self.model_name,
            base_url=base_url
        )

