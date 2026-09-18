"""Thin boto3 helpers for the Leash agent: tag lookups, SSM run-and-poll, latest CloudWatch metric.

Clients are created lazily and cached so unit tests can swap `client()` for a fake factory.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

ENV_TAG_KEY = os.environ.get("ENV_TAG_KEY", "env")
UNKNOWN_ENV = "unknown"

_CLIENTS: dict = {}


def region() -> str:
    """Region for every client; Lambda sets AWS_REGION at runtime."""
    return os.environ.get("AWS_REGION", "us-east-1")


def client(service: str):
    """Return a cached boto3 client for `service` (tests monkeypatch this function)."""
    if service not in _CLIENTS:
        _CLIENTS[service] = boto3.client(service, region_name=region())
    return _CLIENTS[service]


def _tags_to_dict(tags: list, key_name: str = "Key", value_name: str = "Value") -> dict:
    return {t.get(key_name, ""): t.get(value_name, "") for t in tags or []}


def _env_from(tags: dict) -> str:
    return tags.get(ENV_TAG_KEY) or UNKNOWN_ENV


# --- EC2 -------------------------------------------------------------------


def describe_instance(instance_id: str) -> dict:
    """Return {"env", "state", "name", "tags"} for one instance; env is "unknown" if untagged."""
    resp = client("ec2").describe_instances(InstanceIds=[instance_id])
    reservations = resp.get("Reservations", [])
    if not reservations or not reservations[0].get("Instances"):
        raise ValueError(f"instance {instance_id} not found")
    inst = reservations[0]["Instances"][0]
    tags = _tags_to_dict(inst.get("Tags", []))
    return {
        "env": _env_from(tags),
        "state": inst.get("State", {}).get("Name", "unknown"),
        "name": tags.get("Name", ""),
        "tags": tags,
    }


def instance_env(instance_id: str) -> str:
    try:
        return describe_instance(instance_id)["env"]
    except Exception:
        return UNKNOWN_ENV


# --- ECS -------------------------------------------------------------------


def describe_service(cluster: str, service: str) -> dict:
    """Return {"env", "running", "desired", "status", "arn"} for an ECS service."""
    ecs = client("ecs")
    resp = ecs.describe_services(cluster=cluster, services=[service])
    services = resp.get("services", [])
    if not services:
        raise ValueError(f"service {service} not found in cluster {cluster}")
    svc = services[0]
    arn = svc.get("serviceArn", "")
    try:
        # ECS tags live on the service ARN, not in describe_services by default:
        # https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ListTagsForResource.html
        tag_resp = ecs.list_tags_for_resource(resourceArn=arn)
        tags = _tags_to_dict(tag_resp.get("tags", []), "key", "value")
    except Exception:
        tags = {}
    return {
        "env": _env_from(tags),
        "running": svc.get("runningCount", 0),
        "desired": svc.get("desiredCount", 0),
        "status": svc.get("status", "unknown"),
        "arn": arn,
    }


def service_env(cluster: str, service: str) -> str:
    try:
        return describe_service(cluster, service)["env"]
    except Exception:
        return UNKNOWN_ENV


# --- Auto Scaling -----------------------------------------------------------


def asg_env(asg_name: str) -> str:
    """Env tag of an Auto Scaling group via autoscaling:DescribeTags filtered by group name."""
    try:
        resp = client("autoscaling").describe_tags(
            Filters=[{"Name": "auto-scaling-group", "Values": [asg_name]}]
        )
        tags = _tags_to_dict(resp.get("Tags", []))
        return _env_from(tags)
    except Exception:
        return UNKNOWN_ENV


# --- SSM -------------------------------------------------------------------


def ssm_run(instance_id: str, commands: list[str], timeout_s: int = 90, poll_s: int = 3) -> dict:
    """Run a shell script on an instance via AWS-RunShellScript and poll until it finishes.

    Returns {"status", "stdout", "stderr", "command_id"}. Status is "TimedOut" if the
    invocation is still running after `timeout_s`.
    """
    ssm = client("ssm")
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        TimeoutSeconds=max(30, timeout_s),
    )
    command_id = resp["Command"]["CommandId"]
    deadline = time.time() + timeout_s
    result = {"status": "TimedOut", "stdout": "", "stderr": "", "command_id": command_id}
    while time.time() < deadline:
        try:
            inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ClientError as exc:
            # The invocation record can lag send_command by a few seconds.
            if exc.response.get("Error", {}).get("Code") == "InvocationDoesNotExist":
                time.sleep(poll_s)
                continue
            raise
        status = inv.get("Status", "")
        if status not in ("Pending", "InProgress", "Delayed"):
            result.update(
                status=status,
                stdout=inv.get("StandardOutputContent", ""),
                stderr=inv.get("StandardErrorContent", ""),
            )
            return result
        time.sleep(poll_s)
    return result


# --- CloudWatch -------------------------------------------------------------


def latest_metric(namespace: str, metric_name: str, dimensions: dict, minutes: int = 15) -> dict | None:
    """Latest datapoint of a metric. `dimensions` may be partial (e.g. only InstanceId):
    list_metrics finds the full dimension set, which GetMetricStatistics requires to match exactly.
    """
    cw = client("cloudwatch")
    dim_list = [{"Name": k, "Value": v} for k, v in dimensions.items()]
    listed = cw.list_metrics(Namespace=namespace, MetricName=metric_name, Dimensions=dim_list)
    metrics = listed.get("Metrics", [])
    if not metrics:
        return None
    # Prefer the root filesystem when several disks report.
    chosen = next(
        (m for m in metrics if {"Name": "path", "Value": "/"} in m.get("Dimensions", [])),
        metrics[0],
    )
    now = datetime.now(timezone.utc)
    stats = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=chosen.get("Dimensions", dim_list),
        StartTime=now - timedelta(minutes=minutes),
        EndTime=now,
        Period=60,
        Statistics=["Maximum"],
    )
    points = sorted(stats.get("Datapoints", []), key=lambda p: p["Timestamp"])
    if not points:
        return None
    last = points[-1]
    return {"value": last["Maximum"], "timestamp": last["Timestamp"].isoformat(), "dimensions": chosen.get("Dimensions", [])}
