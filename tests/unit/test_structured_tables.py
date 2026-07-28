"""Phase 5 单元测试：结构化记忆表（Tables 白名单 + 懒建表 + 工具）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from xiaopaw.config.flags import FeatureFlags
from xiaopaw.config.validator import MemoryConfig
from xiaopaw.memory.remote_memory import RemoteMemoryStore
from xiaopaw.tools.structured_record_tools import (
    QueryStructuredRecordsTool,
    SaveStructuredRecordTool,
    _coerce_dict,
)


def _make_store() -> RemoteMemoryStore:
    store = RemoteMemoryStore()
    cfg = MemoryConfig(
        remote_base_url="http://localhost:8000/api/v1",
        remote_api_key="amk_test",
    )
    flags = SimpleNamespace(enable_remote_memory=True)
    store.init_from_config(cfg, flags)
    return store


def _resp(status_code: int = 200, payload: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = payload or {}
    return resp


class TestFlagAndConfig:
    def test_flag_default_off(self):
        assert FeatureFlags().enable_structured_tables is False

    def test_builtin_whitelist(self):
        cfg = MemoryConfig()
        assert set(cfg.structured_tables) == {"todo", "expense"}
        assert {f["name"] for f in cfg.structured_tables["todo"]} == {
            "title", "due_date", "status",
        }

    def test_store_loads_whitelist(self):
        store = _make_store()
        assert store.allowed_tables == ["expense", "todo"]
        assert store.table_schema("nope") is None


class TestEnsureTableSync:
    def test_disabled_store(self):
        assert RemoteMemoryStore().ensure_table_sync("todo") is False

    def test_non_whitelist_rejected(self):
        store = _make_store()
        with patch("httpx.request") as req:
            assert store.ensure_table_sync("secrets") is False
            req.assert_not_called()

    def test_success_cached_once(self):
        store = _make_store()
        with patch("httpx.request", return_value=_resp(201, {"success": True})) as req:
            assert store.ensure_table_sync("todo") is True
            assert store.ensure_table_sync("todo") is True
            assert req.call_count == 1

    def test_already_exists_treated_ok(self):
        store = _make_store()
        with patch(
            "httpx.request",
            return_value=_resp(400, text='{"error": "Table already exists"}'),
        ):
            assert store.ensure_table_sync("todo") is True

    def test_server_error_not_cached(self):
        store = _make_store()
        with patch("httpx.request", return_value=_resp(500, text="boom")):
            assert store.ensure_table_sync("todo") is False
        assert "todo" not in store._ensured_tables


class TestRecordSyncMethods:
    def test_add_record_returns_id_and_counts(self):
        store = _make_store()
        store._ensured_tables.add("todo")
        with patch(
            "httpx.request", return_value=_resp(201, {"success": True, "record_id": 7}),
        ) as req:
            assert store.add_record_sync("todo", {"title": "交周报"}) == 7
        assert store.stats()["table_write_total"] == 1
        assert store.stats()["table_write_failed"] == 0
        _, kwargs = req.call_args
        assert kwargs["json"] == {"record": {"title": "交周报"}}

    def test_add_record_failure_counted(self):
        store = _make_store()
        store._ensured_tables.add("todo")
        with patch("httpx.request", return_value=_resp(500, text="boom")):
            assert store.add_record_sync("todo", {"title": "x"}) is None
        assert store.stats()["table_write_failed"] == 1

    def test_update_record_uses_query_param(self):
        store = _make_store()
        store._ensured_tables.add("todo")
        with patch("httpx.request", return_value=_resp(200, {"success": True})) as req:
            assert store.update_record_sync("todo", 7, {"status": "done"}) is True
        _, kwargs = req.call_args
        assert kwargs["params"] == {"record_id": 7}
        assert kwargs["json"] == {"updates": {"status": "done"}}

    def test_query_records_success(self):
        store = _make_store()
        with patch(
            "httpx.request",
            return_value=_resp(200, {"success": True, "records": [{"id": 1}]}),
        ):
            assert store.query_records_sync("todo", {"status": "pending"}) == [{"id": 1}]

    def test_query_non_whitelist_none(self):
        store = _make_store()
        assert store.query_records_sync("secrets") is None

    def test_query_http_error_none(self):
        store = _make_store()
        with patch("httpx.request", return_value=_resp(500, text="boom")):
            assert store.query_records_sync("todo") is None


class TestSaveStructuredRecordTool:
    def _patched_store(self, **attrs):
        store = MagicMock()
        store.is_enabled = attrs.pop("is_enabled", True)
        schemas = {
            "todo": [{"name": "title"}, {"name": "due_date"}, {"name": "status"}],
        }
        store.table_schema.side_effect = schemas.get
        store.allowed_tables = ["expense", "todo"]
        for key, value in attrs.items():
            setattr(store, key, value)
        return patch(
            "xiaopaw.tools.structured_record_tools.remote_memory_store", store,
        ), store

    def test_non_whitelist_table(self):
        ctx, _ = self._patched_store()
        with ctx:
            out = SaveStructuredRecordTool()._run(
                table_name="secrets", record={"title": "x"},
            )
        assert "不在白名单" in out

    def test_unknown_field_rejected(self):
        ctx, store = self._patched_store()
        with ctx:
            out = SaveStructuredRecordTool()._run(
                table_name="todo", record={"title": "x", "hacker": "y"},
            )
        assert "不在表" in out
        store.add_record_sync.assert_not_called()

    def test_empty_record(self):
        ctx, _ = self._patched_store()
        with ctx:
            assert "不能为空" in SaveStructuredRecordTool()._run(
                table_name="todo", record={},
            )

    def test_disabled_hint(self):
        ctx, _ = self._patched_store(is_enabled=False)
        with ctx:
            assert "未启用" in SaveStructuredRecordTool()._run(
                table_name="todo", record={"title": "x"},
            )

    def test_add_success(self):
        ctx, store = self._patched_store()
        store.add_record_sync.return_value = 3
        with ctx:
            out = SaveStructuredRecordTool()._run(
                table_name="Todo", record={"title": "交周报", "status": "pending"},
            )
        store.add_record_sync.assert_called_once_with(
            "todo", {"title": "交周报", "status": "pending"},
        )
        assert "已保存" in out and "#3" in out

    def test_record_id_switches_to_update(self):
        ctx, store = self._patched_store()
        store.update_record_sync.return_value = True
        with ctx:
            out = SaveStructuredRecordTool()._run(
                table_name="todo", record={"record_id": "7", "status": "done"},
            )
        store.update_record_sync.assert_called_once_with("todo", 7, {"status": "done"})
        store.add_record_sync.assert_not_called()
        assert "已更新" in out

    def test_invalid_record_id(self):
        ctx, _ = self._patched_store()
        with ctx:
            out = SaveStructuredRecordTool()._run(
                table_name="todo", record={"record_id": "abc", "status": "done"},
            )
        assert "不是有效整数" in out

    def test_record_as_json_string_coerced(self):
        ctx, store = self._patched_store()
        store.add_record_sync.return_value = 1
        with ctx:
            out = SaveStructuredRecordTool()._run(
                table_name="todo", record='{"title": "买牛奶"}',
            )
        store.add_record_sync.assert_called_once_with("todo", {"title": "买牛奶"})
        assert "已保存" in out


class TestQueryStructuredRecordsTool:
    def _patched_store(self, **attrs):
        store = MagicMock()
        store.is_enabled = attrs.pop("is_enabled", True)
        store.table_schema.side_effect = {
            "todo": [{"name": "title"}, {"name": "due_date"}, {"name": "status"}],
        }.get
        store.allowed_tables = ["expense", "todo"]
        for key, value in attrs.items():
            setattr(store, key, value)
        return patch(
            "xiaopaw.tools.structured_record_tools.remote_memory_store", store,
        ), store

    def test_non_whitelist_table(self):
        ctx, _ = self._patched_store()
        with ctx:
            assert "不在白名单" in QueryStructuredRecordsTool()._run(table_name="secrets")

    def test_service_down(self):
        ctx, store = self._patched_store()
        store.query_records_sync.return_value = None
        with ctx:
            assert "查询失败" in QueryStructuredRecordsTool()._run(table_name="todo")

    def test_no_match(self):
        ctx, store = self._patched_store()
        store.query_records_sync.return_value = []
        with ctx:
            assert "没有匹配" in QueryStructuredRecordsTool()._run(
                table_name="todo", filters={"status": "pending"},
            )

    def test_success_formats_lines(self):
        ctx, store = self._patched_store()
        store.query_records_sync.return_value = [
            {"id": 1, "title": "交周报"}, {"id": 2, "title": "买牛奶"},
        ]
        with ctx:
            out = QueryStructuredRecordsTool()._run(table_name="todo")
        assert "2 条" in out and "交周报" in out


class TestCoerceDict:
    def test_passthrough(self):
        assert _coerce_dict({"a": 1}) == {"a": 1}

    def test_json_string(self):
        assert _coerce_dict('{"a": 1}') == {"a": 1}

    def test_garbage_returns_empty(self):
        assert _coerce_dict("not json") == {}
        assert _coerce_dict(None) == {}
