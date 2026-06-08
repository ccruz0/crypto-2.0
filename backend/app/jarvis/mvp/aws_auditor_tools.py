"""Read-only AWS inventory tools for the Jarvis AWS Auditor agent."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_RISKY_PORTS = {22, 3389, 5432, 3306, 6379, 27017, 9200, 5601}
_SNAPSHOT_AGE_DAYS = 90
_REQUIRED_TAGS = ("Environment", "Project", "Owner")


def _aws_region() -> str:
    return (
        os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("JARVIS_BEDROCK_REGION")
        or "ap-southeast-1"
    ).strip()


def _client(service: str):
    import boto3

    return boto3.client(service, region_name=_aws_region())


def _tool_result(tool: str, *, success: bool = True, **payload: Any) -> dict[str, Any]:
    base = {
        "tool": tool,
        "success": success,
        "region": _aws_region(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(payload)
    return base


def _safe_call(tool: str, fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        logger.warning("aws_auditor tool=%s error=%s", tool, exc)
        return _tool_result(tool, success=False, error=str(exc))


def get_ec2_inventory() -> dict[str, Any]:
    """List EC2 instances with state and tagging (read-only)."""

    def _run() -> dict[str, Any]:
        ec2 = _client("ec2")
        paginator = ec2.get_paginator("describe_instances")
        instances: list[dict[str, Any]] = []
        for page in paginator.paginate():
            for reservation in page.get("Reservations") or []:
                for inst in reservation.get("Instances") or []:
                    tags = {t["Key"]: t["Value"] for t in inst.get("Tags") or [] if t.get("Key")}
                    state = (inst.get("State") or {}).get("Name", "unknown")
                    launch = inst.get("LaunchTime")
                    instances.append(
                        {
                            "instance_id": inst.get("InstanceId"),
                            "state": state,
                            "instance_type": inst.get("InstanceType"),
                            "launch_time": launch.isoformat() if launch else None,
                            "tags": tags,
                            "has_tags": bool(tags),
                            "stopped": state == "stopped",
                            "idle_candidate": state in ("stopped", "stopping"),
                        }
                    )
        stopped = [i for i in instances if i["stopped"]]
        untagged = [i for i in instances if not i["has_tags"]]
        return _tool_result(
            "get_ec2_inventory",
            total=len(instances),
            running=sum(1 for i in instances if i["state"] == "running"),
            stopped_count=len(stopped),
            stopped_instances=stopped[:50],
            untagged_count=len(untagged),
            untagged_instances=[i["instance_id"] for i in untagged[:50]],
            instances=instances[:100],
        )

    return _safe_call("get_ec2_inventory", _run)


def get_ebs_inventory() -> dict[str, Any]:
    """List EBS volumes; flag unattached (available) volumes (read-only)."""

    def _run() -> dict[str, Any]:
        ec2 = _client("ec2")
        paginator = ec2.get_paginator("describe_volumes")
        volumes: list[dict[str, Any]] = []
        for page in paginator.paginate():
            for vol in page.get("Volumes") or []:
                tags = {t["Key"]: t["Value"] for t in vol.get("Tags") or [] if t.get("Key")}
                state = vol.get("State", "unknown")
                size = vol.get("Size", 0)
                volumes.append(
                    {
                        "volume_id": vol.get("VolumeId"),
                        "state": state,
                        "size_gb": size,
                        "volume_type": vol.get("VolumeType"),
                        "attached_to": (vol.get("Attachments") or [{}])[0].get("InstanceId"),
                        "tags": tags,
                        "unattached": state == "available",
                    }
                )
        unattached = [v for v in volumes if v["unattached"]]
        monthly_waste = sum(v["size_gb"] for v in unattached) * 0.10
        return _tool_result(
            "get_ebs_inventory",
            total=len(volumes),
            unattached_count=len(unattached),
            unattached_volumes=unattached[:50],
            estimated_monthly_waste_usd=round(monthly_waste, 2),
            volumes=volumes[:100],
        )

    return _safe_call("get_ebs_inventory", _run)


def get_snapshot_inventory() -> dict[str, Any]:
    """List owned EBS snapshots; flag snapshots older than 90 days (read-only)."""

    def _run() -> dict[str, Any]:
        ec2 = _client("ec2")
        cutoff = datetime.now(timezone.utc) - timedelta(days=_SNAPSHOT_AGE_DAYS)
        paginator = ec2.get_paginator("describe_snapshots")
        snapshots: list[dict[str, Any]] = []
        for page in paginator.paginate(OwnerIds=["self"]):
            for snap in page.get("Snapshots") or []:
                start = snap.get("StartTime")
                is_old = bool(start and start < cutoff)
                size = snap.get("VolumeSize", 0)
                snapshots.append(
                    {
                        "snapshot_id": snap.get("SnapshotId"),
                        "volume_id": snap.get("VolumeId"),
                        "start_time": start.isoformat() if start else None,
                        "size_gb": size,
                        "description": (snap.get("Description") or "")[:120],
                        "old": is_old,
                    }
                )
        old_snaps = [s for s in snapshots if s["old"]]
        monthly_waste = sum(s["size_gb"] for s in old_snaps) * 0.05
        return _tool_result(
            "get_snapshot_inventory",
            total=len(snapshots),
            old_count=len(old_snaps),
            old_snapshots=old_snaps[:50],
            estimated_monthly_waste_usd=round(monthly_waste, 2),
            snapshots=snapshots[:100],
        )

    return _safe_call("get_snapshot_inventory", _run)


def get_eip_inventory() -> dict[str, Any]:
    """List Elastic IPs; flag addresses not attached to instances (read-only)."""

    def _run() -> dict[str, Any]:
        ec2 = _client("ec2")
        resp = ec2.describe_addresses()
        addresses: list[dict[str, Any]] = []
        for addr in resp.get("Addresses") or []:
            attached = bool(addr.get("InstanceId") or addr.get("NetworkInterfaceId"))
            addresses.append(
                {
                    "allocation_id": addr.get("AllocationId"),
                    "public_ip": addr.get("PublicIp"),
                    "instance_id": addr.get("InstanceId"),
                    "domain": addr.get("Domain"),
                    "attached": attached,
                }
            )
        unattached = [a for a in addresses if not a["attached"]]
        return _tool_result(
            "get_eip_inventory",
            total=len(addresses),
            unattached_count=len(unattached),
            unattached_eips=unattached,
            estimated_monthly_waste_usd=round(len(unattached) * 3.65, 2),
            addresses=addresses,
        )

    return _safe_call("get_eip_inventory", _run)


def get_security_group_inventory() -> dict[str, Any]:
    """List security groups; flag rules with risky public exposure (read-only)."""

    def _run() -> dict[str, Any]:
        ec2 = _client("ec2")
        resp = ec2.describe_security_groups()
        groups: list[dict[str, Any]] = []
        risky: list[dict[str, Any]] = []
        for sg in resp.get("SecurityGroups") or []:
            sg_id = sg.get("GroupId")
            sg_name = sg.get("GroupName")
            risky_rules: list[dict[str, Any]] = []
            for perm in sg.get("IpPermissions") or []:
                from_port = perm.get("FromPort")
                to_port = perm.get("ToPort")
                for ip_range in perm.get("IpRanges") or []:
                    cidr = ip_range.get("CidrIp", "")
                    if cidr in ("0.0.0.0/0", "::/0"):
                        port = from_port or to_port
                        if port is None or port in _RISKY_PORTS or (from_port and from_port <= 1024):
                            risky_rules.append(
                                {
                                    "protocol": perm.get("IpProtocol"),
                                    "from_port": from_port,
                                    "to_port": to_port,
                                    "cidr": cidr,
                                }
                            )
            entry = {
                "group_id": sg_id,
                "group_name": sg_name,
                "vpc_id": sg.get("VpcId"),
                "risky_rules": risky_rules,
                "has_risky_exposure": bool(risky_rules),
            }
            groups.append(entry)
            if risky_rules:
                risky.append(entry)
        return _tool_result(
            "get_security_group_inventory",
            total=len(groups),
            risky_count=len(risky),
            risky_security_groups=risky[:50],
            security_groups=groups[:100],
        )

    return _safe_call("get_security_group_inventory", _run)


def get_cost_summary() -> dict[str, Any]:
    """Fetch AWS cost summary for the last 30 days via Cost Explorer (read-only)."""

    def _run() -> dict[str, Any]:
        ce = _client("ce")
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=30)
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )
        periods = resp.get("ResultsByTime") or []
        total = 0.0
        by_period: list[dict[str, Any]] = []
        for period in periods:
            amount = float(
                (period.get("Total") or {})
                .get("UnblendedCost", {})
                .get("Amount", 0)
                or 0
            )
            total += amount
            by_period.append(
                {
                    "start": period.get("TimePeriod", {}).get("Start"),
                    "end": period.get("TimePeriod", {}).get("End"),
                    "amount_usd": round(amount, 2),
                }
            )
        service_resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        services: list[dict[str, Any]] = []
        for group in (service_resp.get("ResultsByTime") or [{}])[0].get("Groups") or []:
            svc = (group.get("Keys") or ["Unknown"])[0]
            amt = float(
                (group.get("Metrics") or {})
                .get("UnblendedCost", {})
                .get("Amount", 0)
                or 0
            )
            if amt > 0.01:
                services.append({"service": svc, "amount_usd": round(amt, 2)})
        services.sort(key=lambda x: x["amount_usd"], reverse=True)
        return _tool_result(
            "get_cost_summary",
            period_days=30,
            total_usd=round(total, 2),
            by_period=by_period,
            top_services=services[:15],
            anomalies=[],
        )

    return _safe_call("get_cost_summary", _run)


def get_resource_tag_audit() -> dict[str, Any]:
    """Audit EC2/EBS resources missing required tags (read-only)."""

    def _run() -> dict[str, Any]:
        ec2 = _client("ec2")
        untagged: list[dict[str, Any]] = []

        inst_paginator = ec2.get_paginator("describe_instances")
        for page in inst_paginator.paginate():
            for reservation in page.get("Reservations") or []:
                for inst in reservation.get("Instances") or []:
                    tags = {t["Key"]: t["Value"] for t in inst.get("Tags") or [] if t.get("Key")}
                    missing = [t for t in _REQUIRED_TAGS if t not in tags]
                    if missing:
                        untagged.append(
                            {
                                "resource_type": "ec2",
                                "resource_id": inst.get("InstanceId"),
                                "missing_tags": missing,
                            }
                        )

        vol_paginator = ec2.get_paginator("describe_volumes")
        for page in vol_paginator.paginate():
            for vol in page.get("Volumes") or []:
                tags = {t["Key"]: t["Value"] for t in vol.get("Tags") or [] if t.get("Key")}
                missing = [t for t in _REQUIRED_TAGS if t not in tags]
                if missing:
                    untagged.append(
                        {
                            "resource_type": "ebs",
                            "resource_id": vol.get("VolumeId"),
                            "missing_tags": missing,
                        }
                    )

        return _tool_result(
            "get_resource_tag_audit",
            required_tags=list(_REQUIRED_TAGS),
            untagged_count=len(untagged),
            untagged_resources=untagged[:100],
        )

    return _safe_call("get_resource_tag_audit", _run)


AWS_AUDITOR_TOOLS: frozenset[str] = frozenset(
    {
        "get_ec2_inventory",
        "get_ebs_inventory",
        "get_snapshot_inventory",
        "get_eip_inventory",
        "get_security_group_inventory",
        "get_cost_summary",
        "get_resource_tag_audit",
    }
)

_AWS_AUDITOR_HANDLERS = {
    "get_ec2_inventory": get_ec2_inventory,
    "get_ebs_inventory": get_ebs_inventory,
    "get_snapshot_inventory": get_snapshot_inventory,
    "get_eip_inventory": get_eip_inventory,
    "get_security_group_inventory": get_security_group_inventory,
    "get_cost_summary": get_cost_summary,
    "get_resource_tag_audit": get_resource_tag_audit,
}


def run_aws_auditor_tool(name: str) -> dict[str, Any]:
    """Execute one AWS auditor read-only tool."""
    tool = (name or "").strip()
    handler = _AWS_AUDITOR_HANDLERS.get(tool)
    if handler is None:
        return _tool_result(tool, success=False, error=f"Unknown AWS auditor tool: {tool}")
    return handler()
