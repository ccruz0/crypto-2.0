"""Sync secrets to/from AWS Systems Manager Parameter Store."""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger(__name__)

DEFAULT_REGION = "ap-southeast-1"
PARAM_PREFIX = "/secret-console"


def get_region() -> str:
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or DEFAULT_REGION
    ).strip() or DEFAULT_REGION


def parameter_name(environment: str, secret_name: str) -> str:
    env = environment.strip().lower()
    name = secret_name.strip()
    return f"{PARAM_PREFIX}/{env}/{name}"


def _client():
    return boto3.client("ssm", region_name=get_region())


def put_secret(environment: str, secret_name: str, value: str, description: str | None = None) -> dict[str, Any]:
    name = parameter_name(environment, secret_name)
    kwargs: dict[str, Any] = {
        "Name": name,
        "Value": value,
        "Type": "SecureString",
        "Overwrite": True,
    }
    if description:
        kwargs["Description"] = description
    try:
        c = _client()
        resp = c.put_parameter(**kwargs)
        log.info("put_parameter name=%s version=%s", name, resp.get("Version"))
        return {"ok": True, "name": name, "version": resp.get("Version")}
    except (ClientError, BotoCoreError) as e:
        log.error("put_parameter failed for %s: %s", name, e)
        raise RuntimeError(f"AWS put_parameter failed: {e}") from e


def get_secret(environment: str, secret_name: str, with_decryption: bool = True) -> str:
    name = parameter_name(environment, secret_name)
    try:
        c = _client()
        resp = c.get_parameter(Name=name, WithDecryption=with_decryption)
        val = resp["Parameter"]["Value"]
        log.info("get_parameter name=%s", name)
        return val
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ParameterNotFound":
            log.warning("parameter not found: %s", name)
            raise KeyError(name) from e
        log.error("get_parameter failed for %s: %s", name, e)
        raise RuntimeError(f"AWS get_parameter failed: {e}") from e
    except BotoCoreError as e:
        log.error("get_parameter failed for %s: %s", name, e)
        raise RuntimeError(f"AWS get_parameter failed: {e}") from e


def delete_secret(environment: str, secret_name: str) -> None:
    name = parameter_name(environment, secret_name)
    try:
        _client().delete_parameter(Name=name)
        log.info("delete_parameter name=%s", name)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ParameterNotFound":
            log.warning("delete_parameter: not found %s", name)
            return
        log.error("delete_parameter failed: %s", e)
        raise RuntimeError(f"AWS delete_parameter failed: {e}") from e
