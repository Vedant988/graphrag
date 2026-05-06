from common.extractors.LLMEntityRelationshipExtractor import (
    LLMEntityRelationshipExtractor,
)

try:
    from common.extractors.GraphExtractor import GraphExtractor
except ModuleNotFoundError:  # Optional dependency: langchain_experimental
    GraphExtractor = None

__all__ = ["LLMEntityRelationshipExtractor", "GraphExtractor"]
