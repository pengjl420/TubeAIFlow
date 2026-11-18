import json

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.api import compute
from app.integrations.compshare import CompShareClient, sign_parameters
from app.providers.compute import ComputeError


def test_official_signature_vector():
    assert sign_parameters({"Action": "DescribeUHostInstance", "Limit": 10,
                            "PublicKey": "someone@example.com1296235120854146120",
                            "Region": "cn-bj2"},
                           "46f09bb9fab4f12dfc160dae12273d5332b5debe") == "4201919d267504385deb93af19e0197870fed36b"


def test_schema_migration_is_repeatable(tmp_path, monkeypatch):
    from app import database
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    monkeypatch.setattr(database, "engine", engine)
    database._apply_migrations()
    database._apply_migrations()
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT MAX(version) FROM schema_migrations").scalar_one() == 27
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(compute_connections)")}
        assert {"credential_id", "instance_id", "config_version"} <= columns
        assert "private_key" not in columns
    engine.dispose()


def test_query_filters_pagination_and_secret_allowlist():
    def handler(request):
        assert str(request.url) == "https://api.compshare.cn"
        body = json.loads(request.content)
        assert body["Action"] == "DescribeCompShareInstance"
        assert body["UHostIds.0"] == "host-1"
        assert body["Offset"] == 20
        assert "private" not in request.content.decode()
        return httpx.Response(200, json={"RetCode": 0, "TotalCount": 21, "UHostSet": [
            {"UHostId": "host-1", "State": "Stopped", "Password": "SECRET",
             "Softwares": [{"URL": "https://secret"}]}]})
    result = CompShareClient("public", "private", transport=httpx.MockTransport(handler)).list_instances(
        instance_id="host-1", offset=20)
    assert result.total == 21
    assert "SECRET" not in result.model_dump_json()
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize("status,body,code", [
    (403, {}, "COMPUTE_AUTH_FAILED"), (429, {}, "COMPUTE_RATE_LIMITED"),
    (200, {"RetCode": 1, "Message": "SECRET"}, "COMPUTE_QUERY_REJECTED"),
    (200, {"RetCode": 0}, "COMPUTE_INVALID_RESPONSE"),
    (302, {}, "COMPUTE_INSTANCE_UNAVAILABLE"),
])
def test_errors_are_sanitized_without_retry(status, body, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    with pytest.raises(ComputeError) as error:
        CompShareClient("public", "private", transport=httpx.MockTransport(handler)).list_instances()
    assert str(error.value) == code
    assert len(calls) == 1


def test_connection_persistence_binding_and_read_only_check(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    secrets = {}
    monkeypatch.setattr(compute.credential_store, "store_secret", lambda key, value: secrets.update({key: value}))
    monkeypatch.setattr(compute.credential_store, "load_secret", lambda key: secrets[key])
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"RetCode": 0, "TotalCount": 1, "UHostSet": [
            {"UHostId": "host-1", "State": "Stopped", "Password": "SECRET"}]})
    monkeypatch.setattr(compute, "CompShareClient", lambda public, private: CompShareClient(
        public, private, transport=httpx.MockTransport(handler)))
    with Session(engine) as session:
        created = compute.create_connection(compute.ConnectionCreate(
            name="test", public_key="PUBLIC_SECRET", private_key="PRIVATE_SECRET"), session)
        row = created["data"]
        assert "SECRET" not in json.dumps(row)
        assert "credential_id" not in row
        with pytest.raises(compute.HTTPException) as error:
            compute.check_connection(row["id"], session)
        assert error.value.status_code == 409
        bound = compute.bind_instance(row["id"], compute.InstanceBinding(instance_id="host-1"), session)
        assert bound["data"]["config_version"] == 2
        checked = compute.check_connection(row["id"], session)
        assert checked["data"]["instance"]["state"] == "Stopped"
        assert checked["data"]["worker_ready"] is False
        assert "SECRET" not in json.dumps(checked)
        assert compute.list_connections(session)["data"][0]["instance_id"] == "host-1"
    assert len(calls) == 2
    assert all(call["Action"] == "DescribeCompShareInstance" for call in calls)


@pytest.mark.parametrize("action", ["start", "stop"])
def test_power_signed_request(action):
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["Action"] == ("StartCompShareInstance" if action == "start" else "StopCompShareInstance")
        assert body["UHostId"] == "host-1"
        assert body["Region"] == "region"
        assert body["Zone"] == "zone"
        signature = body.pop("Signature")
        assert signature == sign_parameters(body, "private")
        return httpx.Response(200, json={"RetCode": 0, "UHostId": "host-1"})
    client = CompShareClient("public", "private", transport=httpx.MockTransport(handler))
    getattr(client, action + "_instance")(region="region", zone="zone", instance_id="host-1")
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "server", "malformed", "rejected"])
def test_power_uncertain_result_never_retried(failure):
    calls = []
    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("secret", request=request)
        return httpx.Response(503 if failure == "server" else 200,
            json={"RetCode": 1, "Message": "SECRET"} if failure == "rejected" else [])
    client = CompShareClient("public", "private", transport=httpx.MockTransport(handler))
    with pytest.raises(ComputeError) as error:
        client.start_instance(region="r", zone="z", instance_id="host-1")
    assert error.value.code == ("COMPUTE_OPERATION_REJECTED" if failure == "rejected" else "COMPUTE_OPERATION_UNKNOWN")
    assert len(calls) == 1


@pytest.mark.parametrize("start,state,spot,allowed", [
    (True, "Stopped", False, True), (False, "Running", False, True),
    (True, "Running", False, False), (False, "Stopped", False, False),
    (False, "Running", True, False), (True, "Starting", False, False),
])
def test_power_checks_live_resource_without_binding(monkeypatch, start, state, spot, allowed):
    from app.models.compute import ComputeConnection
    from app.providers.compute import ComputeInstance, InstancePage
    row = ComputeConnection(id="connection", credential_id="secret", instance_id="unrelated")
    monkeypatch.setattr(compute, "_connection", lambda *args: row)
    monkeypatch.setattr(compute, "_query", lambda *args, **kwargs: InstancePage(total=1, instances=[
        ComputeInstance(instance_id="host-1", state=state, is_spot=spot, region="r", zone="z")]))
    calls = []
    class Client:
        def start_instance(self, **kwargs): calls.append(("start", kwargs))
        def stop_instance(self, **kwargs): calls.append(("stop", kwargs))
    monkeypatch.setattr(compute, "_client", lambda row: Client())
    payload = compute.InstanceBinding(instance_id="host-1")
    if allowed:
        result = compute._power_connection("connection", payload, None, start=start)
        assert result["data"]["accepted"] is True
        assert calls[0][1]["region"] == "r"
    else:
        with pytest.raises(compute.HTTPException) as error:
            compute._power_connection("connection", payload, None, start=start)
        assert error.value.status_code == 409
        assert not calls
    with pytest.raises(compute.HTTPException) as error:
        compute._power_connection("connection", compute.InstanceBinding(instance_id="stale"), None, start=start)
    assert error.value.status_code == 404
