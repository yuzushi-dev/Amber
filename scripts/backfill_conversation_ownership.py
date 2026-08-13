"""Propose and apply explicitly approved legacy conversation ownership.

Dry-run is the default. A write requires the exact SHA-256 of a reviewed
proposal and creates a database-bound receipt for rollback.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

CANDIDATE_SQL = """
WITH candidates AS (
    SELECT
        cs.id AS conversation_id,
        min(k.id) AS api_key_id
    FROM conversation_summaries cs
    JOIN api_keys k
      ON k.name = cs.user_id
     AND k.is_active
    JOIN api_key_tenants akt
      ON akt.api_key_id = k.id
     AND akt.tenant_id = cs.tenant_id
    WHERE cs.api_key_id IS NULL
    GROUP BY cs.id
    HAVING count(DISTINCT k.id) = 1
)
SELECT
    cs.id AS conversation_id,
    cs.tenant_id,
    cs.user_id,
    candidates.api_key_id,
    cs.created_at
FROM candidates
JOIN conversation_summaries cs ON cs.id = candidates.conversation_id
ORDER BY cs.tenant_id, cs.created_at, cs.id
"""

UPDATE_SQL = """
UPDATE conversation_summaries
SET api_key_id = :api_key_id
WHERE id = :conversation_id
  AND tenant_id = :tenant_id
  AND api_key_id IS NULL
"""

ROLLBACK_SQL = """
UPDATE conversation_summaries
SET api_key_id = NULL
WHERE id = :conversation_id
  AND tenant_id = :tenant_id
  AND api_key_id = :api_key_id
"""

DATABASE_FINGERPRINT_SQL = """
SELECT system_identifier::text || '/' || current_database()
FROM pg_control_system()
"""

AUDIT_INSERT_SQL = """
INSERT INTO audit_logs (
    id, tenant_id, timestamp, actor, action, target_type, target_id, changes, metadata_json
) VALUES (
    :run_id, :tenant_id, now(), 'operator', 'conversation_ownership_backfill',
    'conversation_summaries', :run_id, CAST(:changes AS json), CAST(:metadata AS json)
)
"""

AUDIT_SELECT_SQL = """
SELECT changes
FROM audit_logs
WHERE id = :run_id
  AND action = 'conversation_ownership_backfill'
  AND target_id = :run_id
FOR UPDATE
"""

AUDIT_ROLLBACK_SQL = """
UPDATE audit_logs
SET changes = CAST(:changes AS json)
WHERE id = :run_id
  AND action = 'conversation_ownership_backfill'
  AND target_id = :run_id
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="apply an approved proposal")
    mode.add_argument("--rollback", type=Path, help="undo an execution receipt")
    mode.add_argument("--recover-receipt", metavar="RUN_ID", help="reissue a receipt from DB audit")
    parser.add_argument("--approved-report", type=Path, help="reviewed dry-run proposal")
    parser.add_argument("--confirm-report-sha256", help="exact SHA-256 approved by the operator")
    parser.add_argument("--receipt", type=Path, help="new receipt required by --write")
    parser.add_argument("--report", type=Path, help="write the dry-run proposal as JSON")
    parser.add_argument("--database-url", help="override DATABASE_URL")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _parser()
    args = parser.parse_args(argv)
    if (args.write or args.recover_receipt) and not (
        args.approved_report and args.confirm_report_sha256 and args.receipt
    ):
        parser.error(
            "write/recovery requires --approved-report, --confirm-report-sha256, and --receipt"
        )
    if args.approved_report is not None and not args.approved_report.is_file():
        parser.error("--approved-report must reference an existing proposal")
    if args.confirm_report_sha256 is not None and (
        len(args.confirm_report_sha256) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in args.confirm_report_sha256)
    ):
        parser.error("--confirm-report-sha256 must be a 64-character hexadecimal digest")
    if args.receipt is not None and args.receipt.exists():
        parser.error("--receipt must not already exist")
    if args.rollback is not None and not args.rollback.is_file():
        parser.error("--rollback must reference an existing manifest")
    if args.report is not None and args.report.exists():
        parser.error("--report must not already exist")
    return args


def _database_url(override: str | None) -> str:
    if override:
        return override
    if value := os.environ.get("DATABASE_URL"):
        return value
    from src.api.config import get_settings

    return get_settings().db.database_url


def _records(rows) -> list[dict]:
    return [
        {
            "conversation_id": row.conversation_id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "api_key_id": row.api_key_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def write_document(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(document, output, indent=2, sort_keys=True)
        output.write("\n")


def _read_document(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_document(path: Path, kind: str, database: str) -> dict:
    document = _read_document(path)
    if document.get("version") != 1 or document.get("kind") != kind:
        raise ValueError(f"expected version 1 {kind}")
    if document.get("database") != database:
        raise ValueError("document belongs to a different database")
    if not isinstance(document.get("records"), list):
        raise ValueError("document records must be a list")
    return document


def load_receipt(path: Path, database: str) -> dict:
    receipt = _load_document(path, "execution_receipt", database)
    required = ("run_id", "committed_at", "proposal_sha256", "records_sha256")
    if receipt.get("status") != "committed" or any(not receipt.get(key) for key in required):
        raise ValueError("expected a committed receipt with complete run attestation")
    if receipt["records_sha256"] != records_sha256(receipt["records"]):
        raise ValueError("receipt records digest does not match")
    return receipt


def records_sha256(records: list[dict]) -> str:
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_recovery_receipt(
    *,
    run_id: str,
    database: str,
    proposal_sha256: str,
    records: list[dict],
    audit: dict,
) -> dict:
    digest = records_sha256(records)
    expected = {
        "status": "applied",
        "proposal_sha256": proposal_sha256,
        "records_sha256": digest,
        "count": len(records),
    }
    if audit != expected:
        raise ValueError("proposal does not match the applied database audit")
    return {
        "version": 1,
        "kind": "execution_receipt",
        "status": "committed",
        "run_id": run_id,
        "committed_at": datetime.now(UTC).isoformat(),
        "database": database,
        "proposal_sha256": proposal_sha256,
        "records_sha256": digest,
        "records": records,
    }


async def apply_records(connection, sql: str, records: list[dict]) -> int:
    """Apply small, auditable updates with a reliable per-row match count."""
    statement = text(sql)
    matched = 0
    for record in records:
        result = await connection.execute(statement, record)
        matched += result.rowcount
    return matched


async def commit_write(
    *,
    connection,
    transaction,
    records: list[dict],
    database: str,
    proposal_sha256: str,
    receipt_path: Path,
    on_receipt=lambda: None,
) -> None:
    """Commit assignments and their DB audit before publishing a receipt."""
    matched = await apply_records(connection, UPDATE_SQL, records)
    if matched != len(records):
        raise RuntimeError(f"update matched {matched}/{len(records)} rows; transaction aborted")

    run_id = str(uuid4())
    digest = records_sha256(records)
    changes = {
        "status": "applied",
        "proposal_sha256": proposal_sha256,
        "records_sha256": digest,
        "count": len(records),
    }
    await connection.execute(
        text(AUDIT_INSERT_SQL),
        {
            "run_id": run_id,
            "tenant_id": records[0]["tenant_id"] if records else "default",
            "changes": json.dumps(changes, sort_keys=True),
            "metadata": json.dumps({"database": database}, sort_keys=True),
        },
    )
    await transaction.commit()

    write_document(
        receipt_path,
        {
            "version": 1,
            "kind": "execution_receipt",
            "status": "committed",
            "run_id": run_id,
            "committed_at": datetime.now(UTC).isoformat(),
            "database": database,
            "proposal_sha256": proposal_sha256,
            "records_sha256": digest,
            "records": records,
        },
    )
    on_receipt()


async def _run(args: argparse.Namespace) -> None:
    engine = create_async_engine(_database_url(args.database_url))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                await connection.execute(text("SET LOCAL statement_timeout = '30s'"))
                database = (await connection.execute(text(DATABASE_FINGERPRINT_SQL))).scalar_one()

                if args.rollback is not None:
                    receipt = load_receipt(args.rollback, database)
                    records = receipt["records"]
                    audit = (
                        await connection.execute(
                            text(AUDIT_SELECT_SQL), {"run_id": receipt["run_id"]}
                        )
                    ).scalar_one_or_none()
                    expected_audit = {
                        "status": "applied",
                        "proposal_sha256": receipt["proposal_sha256"],
                        "records_sha256": receipt["records_sha256"],
                        "count": len(records),
                    }
                    if audit != expected_audit:
                        raise RuntimeError("receipt has no matching applied database audit")
                    matched = await apply_records(connection, ROLLBACK_SQL, records)
                    if matched != len(records):
                        raise RuntimeError(
                            f"rollback matched {matched}/{len(records)} rows; transaction aborted"
                        )
                    rolled_back = dict(expected_audit, status="rolled_back")
                    await connection.execute(
                        text(AUDIT_ROLLBACK_SQL),
                        {
                            "run_id": receipt["run_id"],
                            "changes": json.dumps(rolled_back, sort_keys=True),
                        },
                    )
                    await transaction.commit()
                    print(
                        f"ROLLBACK: restored {len(records)} conversations to legacy NULL ownership"
                    )
                    return

                if args.recover_receipt is not None:
                    approved_sha = file_sha256(args.approved_report)
                    if approved_sha.lower() != args.confirm_report_sha256.lower():
                        raise ValueError("approved report SHA-256 does not match confirmation")
                    proposal = _load_document(args.approved_report, "ownership_proposal", database)
                    audit = (
                        await connection.execute(
                            text(AUDIT_SELECT_SQL), {"run_id": args.recover_receipt}
                        )
                    ).scalar_one_or_none()
                    receipt = build_recovery_receipt(
                        run_id=args.recover_receipt,
                        database=database,
                        proposal_sha256=approved_sha,
                        records=proposal["records"],
                        audit=audit,
                    )
                    write_document(args.receipt, receipt)
                    await transaction.rollback()
                    print(f"RECOVERY: reissued committed receipt: {args.receipt}")
                    return

                rows = (await connection.execute(text(CANDIDATE_SQL))).all()
                records = _records(rows)
                by_tenant: dict[str, int] = {}
                for record in records:
                    tenant_id = record["tenant_id"]
                    by_tenant[tenant_id] = by_tenant.get(tenant_id, 0) + 1

                print(f"Candidates: {len(records)}")
                for tenant_id, count in sorted(by_tenant.items()):
                    print(f"  {tenant_id}: {count}")

                if not args.write:
                    if args.report is not None:
                        write_document(
                            args.report,
                            {
                                "version": 1,
                                "kind": "ownership_proposal",
                                "database": database,
                                "records": records,
                            },
                        )
                        print(f"Report: {args.report}")
                    await transaction.rollback()
                    print("DRY-RUN: no database changes")
                    return

                approved_sha = file_sha256(args.approved_report)
                if approved_sha.lower() != args.confirm_report_sha256.lower():
                    raise ValueError("approved report SHA-256 does not match confirmation")
                approved = _load_document(args.approved_report, "ownership_proposal", database)
                if approved["records"] != records:
                    raise RuntimeError("approved proposal no longer matches current candidates")
                await commit_write(
                    connection=connection,
                    transaction=transaction,
                    records=records,
                    database=database,
                    proposal_sha256=approved_sha,
                    receipt_path=args.receipt,
                )
                print(f"WRITE: assigned {len(records)} conversations; receipt: {args.receipt}")
            except Exception:
                if transaction.is_active:
                    await transaction.rollback()
                raise
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_run(parse_args(argv)))


if __name__ == "__main__":
    main()
