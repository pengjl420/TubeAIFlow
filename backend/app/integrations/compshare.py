"""CompShare control plane. Never return or log raw instance responses."""
import hashlib

import httpx
from pydantic import ValidationError

from app.providers.compute import ComputeError, ComputeInstance, InstancePage


def sign_parameters(parameters: dict, private_key: str) -> str:
    source = "".join(f"{key}{parameters[key]}" for key in sorted(parameters))
    return hashlib.sha1((source + private_key).encode("utf-8")).hexdigest()


class CompShareClient:
    def __init__(self, public_key: str, private_key: str, *, transport=None):
        if not public_key.strip() or not private_key.strip():
            raise ComputeError("COMPUTE_AUTH_FAILED")
        self._public_key = public_key
        self._private_key = private_key
        self._transport = transport

    def list_instances(self, *, region="", zone="", project_id="",
                       instance_id="", offset=0, limit=20) -> InstancePage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        params = {"Action": "DescribeCompShareInstance", "PublicKey": self._public_key,
                  "Limit": limit, "Offset": offset}
        for key, value in (("Region", region), ("Zone", zone),
                           ("ProjectId", project_id), ("UHostIds.0", instance_id)):
            if value:
                params[key] = value
        params["Signature"] = sign_parameters(params, self._private_key)
        # Fixed HTTPS origin, certificate verification and no redirects/retries.
        try:
            with httpx.Client(transport=self._transport, timeout=30,
                              follow_redirects=False) as client:
                response = client.post("https://api.compshare.cn", json=params)
                if response.status_code in (401, 403):
                    raise ComputeError("COMPUTE_AUTH_FAILED")
                if response.status_code == 429:
                    raise ComputeError("COMPUTE_RATE_LIMITED")
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise ComputeError("COMPUTE_QUERY_TIMEOUT") from None
        except (httpx.HTTPError, ValueError):
            raise ComputeError("COMPUTE_INSTANCE_UNAVAILABLE") from None
        try:
            if data.get("RetCode") != 0:
                # Never forward provider Message (may contain credentials).
                raise ComputeError("COMPUTE_QUERY_REJECTED")
            instances = [ComputeInstance(
                instance_id=item["UHostId"], name=item.get("Name", ""),
                state=item.get("State", "unknown"), region=item.get("Region", ""),
                zone=item.get("Zone", ""), gpu_type=item.get("GpuType", ""),
                gpu_count=item.get("GPU", 0), is_spot=item.get("IsSpot", False),
            ) for item in data["UHostSet"]]
            return InstancePage(total=data["TotalCount"], instances=instances)
        except (KeyError, TypeError, AttributeError, ValidationError):
            raise ComputeError("COMPUTE_INVALID_RESPONSE") from None

    def start_instance(self, *, region, zone, project_id="", instance_id):
        self._power("StartCompShareInstance", region, zone, project_id, instance_id)

    def stop_instance(self, *, region, zone, project_id="", instance_id):
        self._power("StopCompShareInstance", region, zone, project_id, instance_id)

    def _power(self, action, region, zone, project_id, instance_id):
        if not region or not zone or not instance_id:
            raise ComputeError("COMPUTE_LOCATION_REQUIRED")
        params = {"Action": action, "Region": region, "Zone": zone,
                  "UHostId": instance_id, "PublicKey": self._public_key}
        if project_id:
            params["ProjectId"] = project_id
        params["Signature"] = sign_parameters(params, self._private_key)
        try:
            with httpx.Client(transport=self._transport, timeout=30, follow_redirects=False) as client:
                response = client.post("https://api.compshare.cn", json=params)
            if response.status_code in (401, 403):
                raise ComputeError("COMPUTE_AUTH_FAILED")
            if response.status_code == 429:
                raise ComputeError("COMPUTE_RATE_LIMITED")
            if response.status_code >= 500:
                raise ComputeError("COMPUTE_OPERATION_UNKNOWN")
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise ComputeError("COMPUTE_OPERATION_UNKNOWN") from None
        if not isinstance(data, dict) or "RetCode" not in data:
            raise ComputeError("COMPUTE_OPERATION_UNKNOWN")
        if data["RetCode"] != 0:
            raise ComputeError("COMPUTE_OPERATION_REJECTED")
        if data.get("UHostId") != instance_id:
            raise ComputeError("COMPUTE_OPERATION_UNKNOWN")
