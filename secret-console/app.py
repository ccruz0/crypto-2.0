"""
Secret Console — local FastAPI app for encrypted secrets and AWS Parameter Store sync.
Run from this directory: uvicorn app:app --reload --port 8765
"""

from __future__ import annotations

import logging
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import aws_sync
import deploy
import inventory
import keychain
import storage
import verify as verify_mod

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("secret-console")

BASE_DIR = Path(__file__).resolve().parent


def _format_apply_notice(result: dict) -> str:
    """Human-readable line for redirect; keeps structured fields in ``result`` for logs/API."""
    ok = result.get("ok")
    msg = result.get("message", "Done")
    pre = result.get("precheck") or {}
    hc = result.get("healthcheck") or {}
    rb = result.get("rollback") or {}
    parts = [f"Apply {'OK' if ok else 'failed'}: {msg}"]
    if pre:
        bits = [f"{k}={v}" for k, v in pre.items() if k != "detail" and v]
        if pre.get("detail"):
            bits.append(f"detail={pre['detail'][:200]}")
        if bits:
            parts.append("precheck[" + "; ".join(bits[:12]) + "]")
    if result.get("backup"):
        parts.append(f"backup={len(result['backup'])} file(s)")
    if hc:
        parts.append(
            f"healthcheck[compose_ps={hc.get('compose_ps')}; exec={hc.get('exec')}]"
        )
    if rb.get("attempted"):
        parts.append(f"rollback[ok={rb.get('ok')}]")
    rep = result.get("report") or {}
    if rep.get("phase"):
        parts.append(f"phase={rep['phase']}")
    return " | ".join(parts)


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Secret Console", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

_fernet = None


def get_fernet():
    global _fernet
    if _fernet is None:
        _fernet = keychain.get_or_create_fernet()
    return _fernet


def _load_records():
    return storage.load_all_secrets(get_fernet())


def _save_records(records):
    storage.save_all_secrets(get_fernet(), records)


def _find_by_name_env(
    records: list[storage.SecretRecord],
    *,
    name: str,
    environment: str,
) -> storage.SecretRecord | None:
    n = name.strip()
    e = environment.strip().lower()
    for rec in records:
        if rec.name == n and rec.environment == e:
            return rec
    return None


def _redirect_index(notice: str | None = None):
    url = "/"
    if notice:
        url = f"/?notice={urllib.parse.quote(notice)}"
    return RedirectResponse(url=url, status_code=303)


@app.on_event("startup")
async def startup():
    storage.ensure_data_dir()
    get_fernet()
    log.info("data directory: %s", storage.DATA_DIR)
    log.info("secrets file: %s", storage.SECRETS_FILE)


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    notice: str | None = None,
    q: str | None = None,
    env: str | None = None,
    category: str | None = None,
    status: str | None = None,
    pf_name: str | None = None,
    pf_env: str | None = None,
    pf_cat: str | None = None,
    pf_notes: str | None = None,
    pf_desc: str | None = None,
):
    records = _load_records()
    all_rows = inventory.build_display_rows(records)
    vault_rows = inventory.filter_rows(
        all_rows,
        q=(q or ""),
        env=(env or ""),
        category=(category or ""),
        status=(status or ""),
    )
    categories = sorted({(r.get("category") or "").strip() for r in all_rows if (r.get("category") or "").strip()})
    prefill = {
        "name": (pf_name or "").strip(),
        "environment": (pf_env or "prod").strip().lower(),
        "category": (pf_cat or "").strip(),
        "notes": (pf_notes or "").strip(),
        "description": (pf_desc or "").strip(),
    }
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "vault_rows": vault_rows,
            "result_count": len(vault_rows),
            "total_count": len(all_rows),
            "catalog_count": len(inventory.INVENTORY),
            "filters": {
                "q": (q or "").strip(),
                "env": (env or "").strip().lower(),
                "category": (category or "").strip(),
                "status": (status or "").strip().lower(),
            },
            "categories": categories,
            "prefill": prefill,
            "notice": notice,
            "data_dir": str(storage.DATA_DIR),
            "region": aws_sync.get_region(),
        },
    )


@app.get("/edit/{secret_id}", response_class=HTMLResponse)
async def edit_form(request: Request, secret_id: str):
    records = _load_records()
    rec = storage.find_by_id(records, secret_id)
    if not rec:
        raise HTTPException(404, "Secret not found")
    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "secret": rec.to_public_dict(include_value=True),
            "region": aws_sync.get_region(),
        },
    )


@app.post("/save")
async def save(
    request: Request,
    name: str = Form(...),
    value: str = Form(""),
    environment: str = Form(...),
    secret_id: str = Form(""),
    category: str = Form(""),
    notes: str = Form(""),
    description: str = Form(""),
):
    records = _load_records()
    sid = secret_id.strip() or None
    if sid:
        rec = storage.find_by_id(records, sid)
        if not rec:
            raise HTTPException(404, "Secret not found")
        if not value.strip():
            value = rec.value_plain
    else:
        if not value.strip():
            return _redirect_index("New secret needs a value.")
    try:
        records, _ = storage.upsert_secret(
            get_fernet(),
            records,
            secret_id=sid,
            name=name,
            environment=environment,
            value=value,
            category=category,
            notes=notes,
            description=description,
        )
        _save_records(records)
    except ValueError as e:
        log.warning("save validation: %s", e)
        return _redirect_index(str(e))
    log.info("saved secret name=%s env=%s", name, environment)
    return _redirect_index("Saved locally (encrypted).")


@app.post("/delete/{secret_id}")
async def delete(secret_id: str):
    records = _load_records()
    try:
        records = storage.delete_secret(records, secret_id)
        _save_records(records)
    except ValueError:
        raise HTTPException(404, "Secret not found")
    return _redirect_index("Deleted from local store.")


@app.post("/sync/{secret_id}")
async def sync_one(secret_id: str):
    records = _load_records()
    rec = storage.find_by_id(records, secret_id)
    if not rec:
        raise HTTPException(404, "Secret not found")
    try:
        aws_sync.put_secret(rec.environment, rec.name, rec.value_plain)
    except Exception as e:
        log.exception("sync failed")
        return _redirect_index(f"AWS sync failed: {e}")
    return _redirect_index(f"Synced to AWS: {aws_sync.parameter_name(rec.environment, rec.name)}")


@app.post("/save-and-sync")
async def save_and_sync(
    name: str = Form(...),
    value: str = Form(""),
    environment: str = Form(...),
    secret_id: str = Form(""),
    category: str = Form(""),
    notes: str = Form(""),
    description: str = Form(""),
):
    records = _load_records()
    sid = secret_id.strip() or None
    if sid:
        rec = storage.find_by_id(records, sid)
        if not rec:
            raise HTTPException(404, "Secret not found")
        if not value.strip():
            value = rec.value_plain
    else:
        if not value.strip():
            return _redirect_index("New secret needs a value before sync.")
    try:
        records, saved = storage.upsert_secret(
            get_fernet(),
            records,
            secret_id=sid,
            name=name,
            environment=environment,
            value=value,
            category=category,
            notes=notes,
            description=description,
        )
        _save_records(records)
        aws_sync.put_secret(saved.environment, saved.name, saved.value_plain)
    except ValueError as e:
        return _redirect_index(str(e))
    except Exception as e:
        log.exception("save-and-sync failed")
        return _redirect_index(f"AWS sync failed: {e}")
    return _redirect_index("Saved and synced to AWS.")


@app.post("/bulk-import")
async def bulk_import(
    blob: str = Form(""),
    environment: str = Form(...),
    category: str = Form(""),
):
    env_l = environment.strip().lower()
    if env_l not in ("lab", "prod"):
        return _redirect_index("Bulk import failed: environment must be lab or prod.")

    records = _load_records()
    imported = 0
    updated = 0
    skipped = 0
    cat = (category or "").strip()

    for raw in (blob or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            skipped += 1
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or not value:
            skipped += 1
            continue
        existing = _find_by_name_env(records, name=name, environment=env_l)
        sid = existing.id if existing else None
        try:
            records, _ = storage.upsert_secret(
                get_fernet(),
                records,
                secret_id=sid,
                name=name,
                environment=env_l,
                value=value,
                category=cat if cat else (existing.category if existing else ""),
                notes=existing.notes if existing else "",
                description=existing.description if existing else "",
            )
            if existing:
                updated += 1
            else:
                imported += 1
        except ValueError:
            skipped += 1

    if imported or updated:
        _save_records(records)
    return _redirect_index(
        f"Bulk import done: imported={imported}, updated={updated}, skipped={skipped}."
    )


@app.post("/apply/{secret_id}")
async def apply_one(secret_id: str):
    records = _load_records()
    rec = storage.find_by_id(records, secret_id)
    if not rec:
        raise HTTPException(404, "Secret not found")
    result = deploy.apply_to_environment(rec.environment, rec.name)
    notice = _format_apply_notice(result)
    if result.get("ok"):
        log.info("apply succeeded for %s (%s): %s", rec.name, rec.environment, result)
    else:
        log.warning("apply failed for %s (%s): %s", rec.name, rec.environment, result)
    return _redirect_index(notice)


@app.post("/verify/{secret_id}")
async def verify_one(secret_id: str):
    records = _load_records()
    rec = storage.find_by_id(records, secret_id)
    if not rec:
        raise HTTPException(404, "Secret not found")
    result = verify_mod.verify_secret(rec.value_plain, rec.environment, rec.name)
    rc = result.get("runtime_checks") or []
    rc_bits = ", ".join(f"{c['var']}={c['detail']}" for c in rc) if rc else ""
    extra = f" [{rc_bits}]" if rc_bits else ""
    summary = (
        f"Verify [{result['status']}]: AWS={result['aws_detail']} "
        f"runtime={result['runtime_detail']}{extra} "
        f"(local {result['local_preview']}, aws {result['aws_preview']}, "
        f"runtime {result['runtime_preview']})"
    )
    return _redirect_index(summary)


@app.get("/api/secrets/{secret_id}/value")
async def api_secret_value(secret_id: str):
    """Return full plaintext for reveal/copy in the local UI only."""
    records = _load_records()
    rec = storage.find_by_id(records, secret_id)
    if not rec:
        # Keep error payload generic to avoid exposing whether a specific name exists.
        raise HTTPException(404, "Not found")
    log.info("value API read id=%s name=%s", secret_id, rec.name)
    return JSONResponse(
        {"ok": True, "value": rec.value_plain},
        headers={
            "Cache-Control": "no-store, no-cache, max-age=0, must-revalidate, private",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/secrets/{secret_id}/from-aws")
async def api_from_aws(secret_id: str):
    """Retrieve current value from Parameter Store (milestone: display preview in UI)."""
    records = _load_records()
    rec = storage.find_by_id(records, secret_id)
    if not rec:
        raise HTTPException(404, "Secret not found")
    pname = aws_sync.parameter_name(rec.environment, rec.name)
    try:
        val = aws_sync.get_secret(rec.environment, rec.name)
    except KeyError:
        return JSONResponse(
            {"ok": False, "parameter_name": pname, "error": "MISSING", "preview": None},
            status_code=404,
        )
    except Exception as e:
        log.exception("from-aws failed")
        raise HTTPException(502, str(e)) from e
    prev = verify_mod.preview_secret_value(val)
    log.info("from-aws preview for %s", pname)
    return {
        "ok": True,
        "parameter_name": pname,
        "preview": prev,
        "length": len(val),
    }


@app.get("/health")
async def health():
    return {"ok": True, "service": "secret-console"}
