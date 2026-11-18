"""Manual compute control; no automatic lifecycle actions."""
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlmodel import Session, select

from app.database import get_session
from app.infrastructure import credential_store
from app.integrations.compshare import CompShareClient
from app.models.compute import ComputeConnection
from app.providers.compute import ComputeError

router = APIRouter(prefix="/compute/connections", tags=["compute"])


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    region: str = Field(default="", max_length=100)
    zone: str = Field(default="", max_length=100)
    project_id: str = Field(default="", max_length=100)
    public_key: SecretStr
    private_key: SecretStr


class InstanceBinding(BaseModel):
    instance_id: str = Field(min_length=1, max_length=100)


def _connection(session, connection_id):
    row = session.get(ComputeConnection, connection_id)
    if row is None:
        raise HTTPException(404, detail={"code": "COMPUTE_CONNECTION_NOT_FOUND", "error": "连接不存在"})
    return row


def _public(row):
    return row.model_dump(exclude={"credential_id"})


def _client(row):
    try:
        value = json.loads(credential_store.load_secret(row.credential_id))
        return CompShareClient(value["public_key"], value["private_key"])
    except (ValueError, KeyError, TypeError):
        raise ComputeError("COMPUTE_AUTH_FAILED") from None


def _query(row, **kwargs):
    try:
        return _client(row).list_instances(region=row.region, zone=row.zone,
                                           project_id=row.project_id, **kwargs)
    except ComputeError as exc:
        raise HTTPException(502, detail={"code": exc.code, "error": "云 GPU 查询失败，请检查凭证、网络和实例配置"}) from None


@router.post("")
def create_connection(payload: ConnectionCreate, session: Session = Depends(get_session)):
    if not payload.public_key.get_secret_value().strip() or not payload.private_key.get_secret_value().strip():
        raise HTTPException(422, detail="公私钥不能为空")
    connection_id = uuid4().hex
    credential_id = "compshare-" + uuid4().hex
    try:
        credential_store.store_secret(credential_id, json.dumps({
            "public_key": payload.public_key.get_secret_value(),
            "private_key": payload.private_key.get_secret_value(),
        }))
    except (OSError, RuntimeError):
        raise HTTPException(503, detail={"code": "COMPUTE_CREDENTIAL_STORE_FAILED", "error": "安全凭证存储不可用"}) from None
    row = ComputeConnection(id=connection_id, credential_id=credential_id,
                            **payload.model_dump(exclude={"public_key", "private_key"}))
    try:
        session.add(row)
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        credential_store.delete_secret(credential_id)
        raise
    return {"success": True, "data": _public(row)}


@router.get("")
def list_connections(session: Session = Depends(get_session)):
    return {"success": True, "data": [_public(row) for row in session.exec(select(ComputeConnection)).all()]}


@router.get("/{connection_id}/instances")
def list_instances(connection_id: str, offset: int = Query(0, ge=0),
                   limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    page = _query(_connection(session, connection_id), offset=offset, limit=limit)
    return {"success": True, "data": page.model_dump()}


@router.put("/{connection_id}/instance")
def bind_instance(connection_id: str, payload: InstanceBinding, session: Session = Depends(get_session)):
    row = _connection(session, connection_id)
    page = _query(row, instance_id=payload.instance_id)
    if not any(item.instance_id == payload.instance_id for item in page.instances):
        raise HTTPException(404, detail="指定实例不存在")
    row.instance_id = payload.instance_id
    row.config_version += 1
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"success": True, "data": _public(row)}


@router.post("/{connection_id}/check")
def check_connection(connection_id: str, session: Session = Depends(get_session)):
    row = _connection(session, connection_id)
    if not row.instance_id:
        raise HTTPException(409, detail="请先绑定实例")
    page = _query(row, instance_id=row.instance_id)
    instance = next((item for item in page.instances if item.instance_id == row.instance_id), None)
    if instance is None:
        raise HTTPException(404, detail="绑定实例已不可用")
    return {"success": True, "data": {"instance": instance.model_dump(), "worker_ready": False,
                                      "management_mode": "manual"}}


def _power_connection(connection_id, payload, session, *, start):
    row = _connection(session, connection_id)
    page = _query(row, instance_id=payload.instance_id)
    instance = next((item for item in page.instances if item.instance_id == payload.instance_id), None)
    if instance is None:
        raise HTTPException(404, detail={"code": "COMPUTE_INSTANCE_NOT_FOUND", "error": "指定实例不可用"})
    if instance.state != ("Stopped" if start else "Running") or (not start and instance.is_spot):
        raise HTTPException(409, detail={"code": "COMPUTE_STATE_CONFLICT", "error": "当前状态不允许此操作，抢占式实例不支持手动关机"})
    try:
        client = _client(row)
        operation = client.start_instance if start else client.stop_instance
        operation(region=instance.region or row.region, zone=instance.zone or row.zone,
                  project_id=row.project_id, instance_id=instance.instance_id)
    except ComputeError as exc:
        raise HTTPException(502, detail={"code": exc.code,
            "error": "启停请求未确认成功，请先检查实例状态，不要直接重复提交"}) from None
    return {"success": True, "data": {"instance_id": instance.instance_id,
            "accepted": True, "expected_state": "Starting" if start else "Stopping"}}


@router.post("/{connection_id}/start")
def start_instance(connection_id: str, payload: InstanceBinding, session: Session = Depends(get_session)):
    return _power_connection(connection_id, payload, session, start=True)


@router.post("/{connection_id}/stop")
def stop_instance(connection_id: str, payload: InstanceBinding, session: Session = Depends(get_session)):
    return _power_connection(connection_id, payload, session, start=False)
