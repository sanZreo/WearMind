"""健康检查与错误处理的契约测试。

这些测试断言的是"如实报告"，而不是"一切正常"：
测试环境刻意把 DATABASE_URL 置空以模拟"未配置"状态，
因此此时 database.state 必须是 not_configured、/health/ready 必须是 503。
如果哪天它们变成了 connected/200，说明配置被意外注入，测试应当失败。

真实数据库连通时的行为由 test_data_isolation.py 的 db_session 夹具覆盖。
"""

from __future__ import annotations


def test_health_returns_structured_json(client):
    resp = client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    assert set(body) == {"status", "process", "database", "llm", "identity", "timestamp"}

    assert body["process"]["state"] == "running"
    assert body["process"]["name"] == "WearMind"
    assert isinstance(body["process"]["uptime_seconds"], (int, float))


def test_health_reports_identity_mode_honestly(client):
    """默认（未开启开发身份）时必须如实说"没有身份"，不能假装已认证。"""
    identity = client.get("/health").json()["identity"]
    assert identity["auth_mode"] == "unauthenticated"
    assert identity["development_identity_allowed"] is False
    assert identity["dev_user_enabled"] is False


def test_health_reports_database_not_configured(client):
    body = client.get("/health").json()
    assert body["database"]["state"] == "not_configured"
    assert body["database"]["latency_ms"] is None
    # 未配置数据库时整体状态不应被判为故障
    assert body["status"] == "ok"


def test_health_does_not_leak_secrets(client):
    raw = client.get("/health").text.lower()
    for forbidden in ("password", "api_key", "postgresql://", "postgresql+psycopg://"):
        assert forbidden not in raw


def test_readiness_is_503_without_database(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["database"]["state"] == "not_configured"


def test_versioned_health_alias(client):
    assert client.get("/api/v1/health").status_code == 200


def test_request_id_header_is_present(client):
    resp = client.get("/health")
    assert resp.headers.get("X-Request-ID")


def test_unknown_route_uses_error_envelope(client):
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"]


def test_root_endpoint(client):
    body = client.get("/").json()
    assert body["name"] == "WearMind"
    assert body["api_prefix"] == "/api/v1"


def test_no_agent_endpoints_yet(client):
    """本阶段不允许出现"看似已实现"的 Agent 接口。"""
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("agent" in p or "recommend" in p for p in paths)
