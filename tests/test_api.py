import pytest
from fastapi.testclient import TestClient

from mamyda_stt.api import Settings, create_app

KEY_A = "test-secret-a-not-for-production-123"
KEY_B = "test-secret-b-not-for-production-456"


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            api_keys={KEY_A: "app-a", KEY_B: "app-b"},
        )
    )
    with TestClient(app) as client:
        yield client


def test_liveness_does_not_expose_models_or_secrets(client):
    assert client.get("/health/live").json() == {"status": "alive"}


@pytest.mark.parametrize("path", ["/v1/models", "/health/ready", "/openapi.json", "/docs"])
def test_private_endpoints_require_auth(client, path):
    assert client.get(path).status_code == 401


def test_wrong_key_is_rejected(client):
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_models_fail_fast_without_engine(client):
    result = client.get("/v1/models", headers={"Authorization": f"Bearer {KEY_A}"})
    assert result.status_code == 200
    model = result.json()["models"][0]
    assert model["id"] == "whisper-base"
    assert model["audio_capable"] is True
    assert model["ready"] is False
    assert model["reason"] == "engine_not_configured"
    assert "test-secret" not in result.text


def test_readiness_is_not_claimed_before_engine_exists(client):
    response = client.get("/health/ready", headers={"Authorization": f"Bearer {KEY_A}"})
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_no_default_credentials(tmp_path):
    with pytest.raises(ValueError, match="API keys"):
        create_app(Settings(data_dir=tmp_path, api_keys={}))


def test_openapi_available_to_authenticated_clients(client):
    response = client.get("/openapi.json", headers={"Authorization": f"Bearer {KEY_B}"})
    assert response.status_code == 200
    assert "/v1/models" in response.json()["paths"]


def test_weak_credentials_rejected(tmp_path):
    with pytest.raises(ValueError, match="32 bytes"):
        create_app(Settings(data_dir=tmp_path, api_keys={"password": "app"}))


def test_installed_engine_is_not_a_claim_of_working_pipeline(tmp_path):
    binary = tmp_path / "whisper-cli"
    binary.touch()
    binary.chmod(0o700)
    weights = tmp_path / "model.bin"
    weights.touch()
    with TestClient(
        create_app(
            Settings(
                data_dir=tmp_path / "data",
                api_keys={KEY_A: "app"},
                whisper_binary=binary,
                whisper_model=weights,
            )
        )
    ) as client:
        result = client.get("/v1/models", headers={"Authorization": f"Bearer {KEY_A}"}).json()
        assert result["models"][0]["reason"] == "pipeline_not_enabled"
        assert result["models"][0]["ready"] is False
