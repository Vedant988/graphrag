# Copyright (c) 2024-2026 TigerGraph, Inc.
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
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
APP_ROOT = ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
os.environ.setdefault(
    "LOG_CONFIG",
    '{"log_file_path":"D:/github/graphrag/.tmp_test_logs","log_max_size":1048576,"log_backup_count":0}',
)

from app.main import app

# main.py uses `import routers` (absolute), so the module is registered as
# "routers.ui" in sys.modules.  We alias it to "app.routers.ui" so that all
# @patch() targets resolve to the same module object.  If app/main.py ever
# changes its import style, this alias must be updated accordingly.
sys.modules.setdefault("app.routers.ui", sys.modules["routers.ui"])

from app.routers.ui import _resolve_llm_config_access, _require_prompt_access


def _creds(username: str = "testuser", password: str = "testpass") -> HTTPBasicCredentials:
    return HTTPBasicCredentials(username=username, password=password)


class TestUISetupUnit(unittest.TestCase):
    """
    Unit tests for /ui/config and /ui/prompts endpoint logic.
    All TigerGraph and LLM calls are mocked — no live service required.

    Test map
    --------
    _resolve_llm_config_access (3)
      1. test_resolve_llm_access_superuser_returns_full
      2. test_resolve_llm_access_graph_admin_returns_chatbot_only
      3. test_resolve_llm_access_globalobserver_raises_403

    GET /ui/config secret stripping (3)
      4. test_get_config_strips_db_password
      5. test_get_config_strips_llm_api_keys
      8. test_get_config_strips_chat_service_api_keys

    GET /ui/config chatbot_only response (1)
      9. test_get_config_chatbot_only_returns_global_chat_info

    _require_prompt_access (1)
      6. test_graph_admin_entity_extraction_prompt_raises_403

    Concurrent save (1)
      7. test_concurrent_llm_save_returns_409
    """

    def setUp(self):
        self.client = TestClient(app)

    # =========================================================================
    # Test 1 – _resolve_llm_config_access returns "full" for superuser
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=(["superuser"], {}))
    def test_resolve_llm_access_superuser_returns_full(self, _mock):
        result = _resolve_llm_config_access(_creds(), graphname=None)
        self.assertEqual(result, "full")

    # =========================================================================
    # Test 2 – _resolve_llm_config_access returns "chatbot_only" for graph admin
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=([], {"mygraph": ["admin"]}))
    def test_resolve_llm_access_graph_admin_returns_chatbot_only(self, _mock):
        result = _resolve_llm_config_access(_creds(), graphname="mygraph")
        self.assertEqual(result, "chatbot_only")

    # =========================================================================
    # Test 3 – _resolve_llm_config_access raises 403 for globalobserver
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=(["globalobserver"], {}))
    def test_resolve_llm_access_globalobserver_raises_403(self, _mock):
        with self.assertRaises(HTTPException) as ctx:
            _resolve_llm_config_access(_creds(), graphname=None)
        self.assertEqual(ctx.exception.status_code, 403)

    # =========================================================================
    # Test 4 – GET /ui/config does NOT return db password
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=(["superuser"], {}))
    @patch(
        "app.routers.ui.db_config",
        {"hostname": "http://test-db", "username": "tigergraph", "password": "super-secret"},
    )
    @patch("app.routers.ui.llm_config", {"completion_service": {"llm_service": "openai"}})
    @patch("app.routers.ui.graphrag_config", {})
    def test_get_config_strips_db_password(self, _mock):
        response = self.client.get("/ui/config", auth=("testuser", "testpass"))
        self.assertEqual(response.status_code, 200)
        db = response.json().get("db_config", {})
        self.assertNotIn("password", db, "'password' must not be returned in db_config")

    # =========================================================================
    # Test 5 – GET /ui/config does NOT return LLM API keys
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=(["superuser"], {}))
    @patch(
        "app.routers.ui.llm_config",
        {
            "authentication_configuration": {"OPENAI_API_KEY": "sk-top"},
            "completion_service": {"llm_service": "openai", "authentication_configuration": {"OPENAI_API_KEY": "sk-c"}},
            "embedding_service": {"embedding_model_service": "openai", "authentication_configuration": {"OPENAI_API_KEY": "sk-e"}},
            "multimodal_service": {"llm_service": "openai", "authentication_configuration": {"OPENAI_API_KEY": "sk-m"}},
        },
    )
    @patch("app.routers.ui.db_config", {"hostname": "http://test-db"})
    @patch("app.routers.ui.graphrag_config", {})
    def test_get_config_strips_llm_api_keys(self, _mock):
        response = self.client.get("/ui/config", auth=("testuser", "testpass"))
        self.assertEqual(response.status_code, 200)
        llm = response.json().get("llm_config", {})
        self.assertNotIn("authentication_configuration", llm)
        for svc in ("completion_service", "embedding_service", "multimodal_service"):
            self.assertNotIn(
                "authentication_configuration",
                llm.get(svc, {}),
                f"authentication_configuration must not be returned in {svc}",
            )

    # =========================================================================
    # Test 8 – GET /ui/config does NOT return chat_service API keys
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=(["superuser"], {}))
    @patch(
        "app.routers.ui.llm_config",
        {
            "authentication_configuration": {"OPENAI_API_KEY": "sk-top"},
            "completion_service": {"llm_service": "openai"},
            "chat_service": {"llm_service": "groq", "authentication_configuration": {"GROQ_API_KEY": "gsk-secret"}},
        },
    )
    @patch("app.routers.ui.db_config", {"hostname": "http://test-db"})
    @patch("app.routers.ui.graphrag_config", {})
    def test_get_config_strips_chat_service_api_keys(self, _mock):
        response = self.client.get("/ui/config", auth=("testuser", "testpass"))
        self.assertEqual(response.status_code, 200)
        llm = response.json().get("llm_config", {})
        chat_svc = llm.get("chat_service", {})
        self.assertNotIn(
            "authentication_configuration",
            chat_svc,
            "authentication_configuration must not be returned in chat_service",
        )

    # =========================================================================
    # Test 9 – GET /ui/config chatbot_only returns global_chat_info
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=([], {"mygraph": ["admin"]}))
    @patch(
        "app.routers.ui.llm_config",
        {
            "completion_service": {"llm_service": "openai", "llm_model": "gpt-4.1-mini"},
        },
    )
    def test_get_config_chatbot_only_returns_global_chat_info(self, _mock):
        response = self.client.get(
            "/ui/config?graphname=mygraph", auth=("testuser", "testpass")
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("llm_config_access"), "chatbot_only")
        self.assertIn("global_chat_info", data)
        self.assertEqual(data["global_chat_info"]["llm_service"], "openai")
        self.assertEqual(data["global_chat_info"]["llm_model"], "gpt-4.1-mini")
        # No graph-specific chat_service exists, so chatbot_config should be None
        self.assertIsNone(data.get("chatbot_config"))

    # =========================================================================
    # Test 6 – graph admin editing entity_extraction prompt raises 403
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=([], {"mygraph": ["admin"]}))
    def test_graph_admin_entity_extraction_prompt_raises_403(self, _mock):
        response = self.client.post(
            "/ui/prompts",
            json={
                "graphname": "mygraph",
                "prompt_type": "entity_relationship",
                "editable_content": "Extract only the most important entities.",
            },
            auth=("testuser", "testpass"),
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("chatbot", response.json()["detail"].lower())

    # =========================================================================
    # Test 7 – concurrent LLM save returns 409 when lock is held
    # =========================================================================

    @patch("app.routers.ui._get_user_role_details", return_value=(["superuser"], {}))
    @patch("app.routers.ui.auth", return_value=([], MagicMock()))
    @patch("app.routers.ui._ecc_jobs_running", return_value=False)
    def test_concurrent_llm_save_returns_409(self, _mock_ecc, _mock_auth, _mock_roles):
        mock_lock = MagicMock()
        mock_lock.locked.return_value = True
        mock_lock.__aenter__ = AsyncMock()
        mock_lock.__aexit__ = AsyncMock()

        with patch("app.routers.ui.llm_config_lock", mock_lock):
            response = self.client.post(
                "/ui/config/llm",
                json={"completion_service": {"llm_service": "openai", "llm_model": "gpt-4o"}},
                auth=("testuser", "testpass"),
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("in progress", response.json()["detail"].lower())

    @patch("app.routers.ui.ws_basic_auth", return_value=(["mygraph"], MagicMock(graphname="mygraph")))
    @patch("app.routers.ui.auth", return_value=(["mygraph"], MagicMock()))
    @patch(
        "app.routers.ui._run_comparison_pipeline",
        side_effect=[
            {
                "pipeline": "LLM-Only",
                "status": "success",
                "answer": "llm-only answer",
                "latency_seconds": 0.5,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "cost": 0.001, "calls": 1},
                "error": None,
            },
            {
                "pipeline": "Basic RAG",
                "status": "success",
                "answer": "basic rag answer",
                "latency_seconds": 0.8,
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30, "cost": 0.002, "calls": 2},
                "error": None,
            },
            {
                "pipeline": "GraphRAG",
                "status": "success",
                "answer": "graphrag answer",
                "latency_seconds": 1.1,
                "usage": {"input_tokens": 25, "output_tokens": 11, "total_tokens": 36, "cost": 0.003, "calls": 3},
                "error": None,
            },
        ],
    )
    def test_comparison_endpoint_returns_pipeline_results(
        self, _mock_pipeline, _mock_auth, _mock_ws_auth
    ):
        response = self.client.post(
            "/ui/mygraph/comparison",
            json={"question": "What happened?"},
            auth=("testuser", "testpass"),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["graphname"], "mygraph")
        self.assertEqual(data["question"], "What happened?")
        self.assertEqual(
            [pipeline["pipeline"] for pipeline in data["pipelines"]],
            ["LLM-Only", "Basic RAG", "GraphRAG"],
        )


if __name__ == "__main__":
    unittest.main()
