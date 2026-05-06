import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.py_schemas import Document, DocumentChunk
from common.status import IngestionProgress

SUPPORTAI_INGEST_PATH = ROOT / "graphrag" / "app" / "supportai" / "supportai_ingest.py"
SUPPORTAI_INGEST_SPEC = importlib.util.spec_from_file_location(
    "supportai_ingest_under_test",
    SUPPORTAI_INGEST_PATH,
)
supportai_ingest_under_test = importlib.util.module_from_spec(SUPPORTAI_INGEST_SPEC)
assert SUPPORTAI_INGEST_SPEC.loader is not None
sys.modules["supportai_ingest_under_test"] = supportai_ingest_under_test
SUPPORTAI_INGEST_SPEC.loader.exec_module(supportai_ingest_under_test)
BatchIngestion = supportai_ingest_under_test.BatchIngestion


def make_fake_storage_module(class_name, instance):
    module = types.ModuleType(f"fake_{class_name.lower()}_module")
    klass = MagicMock(return_value=instance)
    setattr(module, class_name, klass)
    return module, klass


class TestBatchIngestion(unittest.TestCase):
    def setUp(self):
        self.embedding_service_mock = MagicMock()
        self.llm_service_mock = MagicMock()
        self.conn_mock = MagicMock()
        self.status_mock = MagicMock()
        self.status_mock.progress = IngestionProgress(num_docs_ingested=0, num_docs=0)
        self.batch_ingestion = BatchIngestion(
            embedding_service=self.embedding_service_mock,
            llm_service=self.llm_service_mock,
            conn=self.conn_mock,
            status=self.status_mock,
        )

    @patch("supportai_ingest_under_test.LLMEntityRelationshipExtractor")
    def test_document_er_extraction_uses_document_text(self, mock_extractor_cls):
        extractor = mock_extractor_cls.return_value
        extractor.extract.return_value = {"nodes": [], "rels": []}
        doc = Document(document_id="doc-1", text="Doc body")
        ingestion = BatchIngestion(
            embedding_service=self.embedding_service_mock,
            llm_service=self.llm_service_mock,
            conn=self.conn_mock,
            status=self.status_mock,
        )

        result = ingestion.document_er_extraction(doc)

        mock_extractor_cls.assert_called_once_with(self.llm_service_mock)
        extractor.extract.assert_called_once_with("Doc body")
        self.assertEqual(result, {"nodes": [], "rels": []})

    @patch("supportai_ingest_under_test.LLMEntityRelationshipExtractor")
    def test_document_er_extraction_uses_chunk_text(self, mock_extractor_cls):
        extractor = mock_extractor_cls.return_value
        extractor.extract.return_value = {"nodes": [], "rels": []}
        chunk = DocumentChunk(document_chunk_id="doc-1_chunk_0", text="Chunk body")
        ingestion = BatchIngestion(
            embedding_service=self.embedding_service_mock,
            llm_service=self.llm_service_mock,
            conn=self.conn_mock,
            status=self.status_mock,
        )

        result = ingestion.document_er_extraction(chunk)

        mock_extractor_cls.assert_called_once_with(self.llm_service_mock)
        extractor.extract.assert_called_once_with("Chunk body")
        self.assertEqual(result, {"nodes": [], "rels": []})

    def test_documents_er_extraction_populates_entities_and_relationships(self):
        docs = [
            Document(document_id="doc-1", text="alpha"),
            Document(document_id="doc-2", text="beta"),
        ]
        responses = [
            {"nodes": [{"id": "A", "type": "Entity", "definition": ""}], "rels": []},
            {"nodes": [], "rels": [{"source": "A", "target": "B", "type": "REL", "definition": ""}]},
        ]

        with patch.object(
            self.batch_ingestion,
            "document_er_extraction",
            side_effect=responses,
        ) as mock_extract:
            self.batch_ingestion.documents_er_extraction(docs)

        self.assertEqual(mock_extract.call_count, 2)
        self.assertEqual(docs[0].entities, responses[0]["nodes"])
        self.assertEqual(docs[0].relationships, responses[0]["rels"])
        self.assertEqual(docs[1].entities, responses[1]["nodes"])
        self.assertEqual(docs[1].relationships, responses[1]["rels"])

    @patch("supportai_ingest_under_test.BatchIngestion._ingest")
    def test_ingest_blobs_s3_file_success(self, mock_ingest):
        fake_blob_store = MagicMock()
        fake_blob_store.read_document.return_value = "Fake document content"
        fake_module, fake_store_cls = make_fake_storage_module(
            "S3BlobStore",
            fake_blob_store,
        )
        mock_ingest.return_value = None

        doc_source = MagicMock()
        doc_source.service = "s3"
        doc_source.chunker = "characters"
        doc_source.chunker_params = {"chunk_size": 11}
        doc_source.service_params = {
            "type": "file",
            "bucket": "test-bucket",
            "key": "directory/",
            "aws_access_key_id": "id",
            "aws_secret_access_key": "key",
        }

        with patch.dict(sys.modules, {"common.storage.s3_blob_store": fake_module}):
            self.batch_ingestion.ingest_blobs(doc_source)

        mock_ingest.assert_called_once()
        fake_store_cls.assert_called_once_with("id", "key")
        fake_blob_store.read_document.assert_called_once_with(
            "test-bucket",
            "directory/",
        )

    @patch("supportai_ingest_under_test.BatchIngestion._ingest")
    def test_ingest_blobs_azure_file_success(self, mock_ingest):
        fake_blob_store = MagicMock()
        fake_blob_store.read_document.return_value = "Fake document content"
        fake_module, fake_store_cls = make_fake_storage_module(
            "AzureBlobStore",
            fake_blob_store,
        )
        mock_ingest.return_value = None

        container_name = "test-bucket"
        blob_name = "directory/file.txt"
        doc_source = MagicMock()
        doc_source.service = "azure"
        doc_source.chunker = "characters"
        doc_source.chunker_params = {"chunk_size": 11}
        doc_source.service_params = {
            "type": "file",
            "bucket": container_name,
            "key": blob_name,
            "azure_connection_string": "connection_string",
        }

        batch_ingestion = BatchIngestion(
            embedding_service=MagicMock(),
            llm_service=MagicMock(),
            conn=MagicMock(),
            status=MagicMock(),
        )

        with patch.dict(sys.modules, {"common.storage.azure_blob_store": fake_module}):
            batch_ingestion.ingest_blobs(doc_source)

        mock_ingest.assert_called_once()
        fake_store_cls.assert_called_once_with("connection_string")
        fake_blob_store.read_document.assert_called_once_with(
            container_name,
            blob_name,
        )

    @patch("supportai_ingest_under_test.BatchIngestion._ingest")
    def test_ingest_blobs_google_file_success(self, mock_ingest):
        fake_blob_store = MagicMock()
        fake_blob_store.read_document.return_value = "Fake document content"
        fake_module, fake_store_cls = make_fake_storage_module(
            "GoogleBlobStore",
            fake_blob_store,
        )
        mock_ingest.return_value = None

        container_name = "test-bucket"
        blob_name = "directory/file.txt"
        doc_source = MagicMock()
        doc_source.service = "google"
        doc_source.chunker = "characters"
        doc_source.chunker_params = {"chunk_size": 11}
        doc_source.service_params = {
            "type": "file",
            "bucket": container_name,
            "key": blob_name,
            "google_credentials": "credentials",
        }

        batch_ingestion = BatchIngestion(
            embedding_service=MagicMock(),
            llm_service=MagicMock(),
            conn=MagicMock(),
            status=MagicMock(),
        )
        with patch.dict(sys.modules, {"common.storage.google_blob_store": fake_module}):
            batch_ingestion.ingest_blobs(doc_source)

        fake_store_cls.assert_called_once_with("credentials")
        fake_blob_store.read_document.assert_called_once_with(
            container_name,
            blob_name,
        )

    @patch("boto3.client")
    def test_ingest_blobs_unsupported_type(self, mock_boto3_client):
        # Test to ensure ValueError is raised for unsupported types without mocking blob stores, as the method should fail before any blob store interaction
        mock_s3 = mock_boto3_client.return_value
        mock_get_object = mock_s3.get_object
        mock_get_object.return_value = {
            "Body": MagicMock(read=lambda: b"Fake document content")
        }

        doc_source = MagicMock()
        doc_source.service = "unsupported"
        doc_source.service_params = {
            "type": "file",
            "bucket": "test-bucket",
            "key": "directory/",
            "aws_access_key_id": "id",
            "aws_secret_access_key": "key",
        }

        ingestion = BatchIngestion(
            embedding_service=MagicMock(),
            llm_service=MagicMock(),
            conn=MagicMock(),
            status=MagicMock(),
        )

        with self.assertRaises(ValueError) as context:
            ingestion.ingest_blobs(doc_source)

        self.assertTrue("Service unsupported not supported" in str(context.exception))


if __name__ == "__main__":
    unittest.main()
