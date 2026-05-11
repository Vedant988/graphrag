from importlib import import_module

from .base_llm import LLM_Model

_PROVIDER_IMPORTS = {
    "AzureOpenAI": ".azure_openai_service",
    "OpenAI": ".openai_service",
    "AWS_SageMaker_Endpoint": ".aws_sagemaker_endpoint",
    "GoogleVertexAI": ".google_vertexai_service",
    "GoogleGenAI": ".google_genai_service",
    "AWSBedrock": ".aws_bedrock_service",
    "Groq": ".groq_llm_service",
    "Ollama": ".ollama",
    "HuggingFaceEndpoint": ".huggingface_endpoint",
    "IBMWatsonX": ".ibm_watsonx_service",
}

__all__ = ["LLM_Model", *_PROVIDER_IMPORTS.keys()]


def __getattr__(name):
    if name == "LLM_Model":
        return LLM_Model
    module_name = _PROVIDER_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
