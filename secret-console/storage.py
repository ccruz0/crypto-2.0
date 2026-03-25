"""Local encrypted JSON storage for secrets."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from encryption import decrypt_value, encrypt_value

log = logging.getLogger(__name__)

DATA_DIR = Path.home() / "secret-console"
SECRETS_FILE = DATA_DIR / "secrets.enc.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SecretRecord:
    id: str
    name: str
    environment: str
    value_plain: str = ""
    last_updated: str = ""
    value_encrypted: str = ""
    category: str = ""
    notes: str = ""
    description: str = ""

    def to_disk_dict(self, fernet: Fernet) -> dict[str, Any]:
        enc = encrypt_value(fernet, self.value_plain) if self.value_plain else self.value_encrypted
        if not enc:
            raise ValueError("secret value is empty")
        ts = self.last_updated or _now_iso()
        return {
            "id": self.id,
            "name": self.name.strip(),
            "environment": self.environment.strip().lower(),
            "value": enc,
            "last_updated": ts,
            "category": (self.category or "").strip(),
            "notes": (self.notes or "").strip(),
            "description": (self.description or "").strip(),
        }

    @classmethod
    def from_disk_dict(cls, row: dict[str, Any], fernet: Fernet) -> SecretRecord:
        rid = row.get("id") or str(uuid.uuid4())
        name = row.get("name", "")
        env = row.get("environment", "prod")
        enc = row.get("value", "")
        plain = decrypt_value(fernet, enc) if enc else ""
        return cls(
            id=rid,
            name=name,
            environment=env,
            value_plain=plain,
            last_updated=row.get("last_updated", ""),
            value_encrypted=enc,
            category=str(row.get("category", "") or ""),
            notes=str(row.get("notes", "") or ""),
            description=str(row.get("description", "") or ""),
        )

    def to_public_dict(self, include_value: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "environment": self.environment,
            "last_updated": self.last_updated,
            "category": self.category,
            "notes": self.notes,
            "description": self.description,
        }
        if include_value:
            d["value"] = self.value_plain
        return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_all_secrets(fernet: Fernet) -> list[SecretRecord]:
    ensure_data_dir()
    if not SECRETS_FILE.exists():
        log.info("no secrets file yet at %s", SECRETS_FILE)
        return []
    raw = SECRETS_FILE.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("secrets file must contain a JSON array")
    out: list[SecretRecord] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            out.append(SecretRecord.from_disk_dict(row, fernet))
        except Exception:
            log.exception("skipping bad row: %s", row.get("name"))
    return out


def save_all_secrets(fernet: Fernet, records: list[SecretRecord]) -> None:
    ensure_data_dir()
    payload = [r.to_disk_dict(fernet) for r in records]
    SECRETS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("wrote %d secrets to %s", len(payload), SECRETS_FILE)


def find_by_id(records: list[SecretRecord], secret_id: str) -> SecretRecord | None:
    for r in records:
        if r.id == secret_id:
            return r
    return None


def upsert_secret(
    fernet: Fernet,
    records: list[SecretRecord],
    *,
    secret_id: str | None,
    name: str,
    environment: str,
    value: str,
    category: str = "",
    notes: str = "",
    description: str = "",
) -> tuple[list[SecretRecord], SecretRecord]:
    env_l = environment.strip().lower()
    name_s = name.strip()
    if not name_s:
        raise ValueError("name is required")
    if env_l not in ("lab", "prod"):
        raise ValueError("environment must be lab or prod")

    cat_s = (category or "").strip()
    notes_s = (notes or "").strip()
    desc_s = (description or "").strip()
    now = _now_iso()
    if secret_id:
        for i, r in enumerate(records):
            if r.id == secret_id:
                for other in records:
                    if other.id != secret_id and other.name == name_s and other.environment == env_l:
                        raise ValueError("another secret already has this name and environment")
                updated = SecretRecord(
                    id=r.id,
                    name=name_s,
                    environment=env_l,
                    value_plain=value,
                    last_updated=now,
                    category=cat_s,
                    notes=notes_s,
                    description=desc_s,
                )
                records[i] = updated
                log.info("updated secret id=%s name=%s env=%s", secret_id, name_s, env_l)
                return records, updated
        raise ValueError("secret not found")

    for r in records:
        if r.name == name_s and r.environment == env_l:
            raise ValueError("secret with this name and environment already exists")
    new = SecretRecord(
        id=str(uuid.uuid4()),
        name=name_s,
        environment=env_l,
        value_plain=value,
        last_updated=now,
        category=cat_s,
        notes=notes_s,
        description=desc_s,
    )
    records.append(new)
    log.info("created secret id=%s name=%s env=%s", new.id, name_s, env_l)
    return records, new


def delete_secret(records: list[SecretRecord], secret_id: str) -> list[SecretRecord]:
    new_list = [r for r in records if r.id != secret_id]
    if len(new_list) == len(records):
        raise ValueError("secret not found")
    log.info("deleted secret id=%s", secret_id)
    return new_list
