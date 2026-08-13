from unittest.mock import AsyncMock, MagicMock

import pytest


def test_candidate_query_requires_active_unique_same_tenant_key():
    from scripts.backfill_conversation_ownership import CANDIDATE_SQL

    sql = " ".join(CANDIDATE_SQL.split()).lower()
    assert "cs.api_key_id is null" in sql
    assert "k.is_active" in sql
    assert "akt.tenant_id = cs.tenant_id" in sql
    assert "having count(distinct k.id) = 1" in sql


def test_write_requires_an_approved_report_hash_and_new_receipt(tmp_path):
    from scripts.backfill_conversation_ownership import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--write"])

    report = tmp_path / "proposal.json"
    report.write_text("{}")
    receipt = tmp_path / "receipt.json"
    args = parse_args(
        [
            "--write",
            "--approved-report",
            str(report),
            "--confirm-report-sha256",
            "a" * 64,
            "--receipt",
            str(receipt),
        ]
    )
    assert args.approved_report == report

    receipt.write_text("do not overwrite")
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--write",
                "--approved-report",
                str(report),
                "--confirm-report-sha256",
                "a" * 64,
                "--receipt",
                str(receipt),
            ]
        )


def test_recovery_requires_run_report_hash_and_new_receipt(tmp_path):
    from scripts.backfill_conversation_ownership import parse_args

    report = tmp_path / "proposal.json"
    report.write_text("{}")
    receipt = tmp_path / "receipt.json"
    args = parse_args(
        [
            "--recover-receipt",
            "run-123",
            "--approved-report",
            str(report),
            "--confirm-report-sha256",
            "a" * 64,
            "--receipt",
            str(receipt),
        ]
    )
    assert args.recover_receipt == "run-123"


def test_default_mode_is_read_only():
    from scripts.backfill_conversation_ownership import parse_args

    args = parse_args([])
    assert args.write is False
    assert args.rollback is None


def test_receipt_cannot_be_confused_with_a_dry_run_report(tmp_path):
    from scripts.backfill_conversation_ownership import load_receipt, write_document

    proposal = tmp_path / "proposal.json"
    write_document(
        proposal,
        {"version": 1, "kind": "ownership_proposal", "database": "cluster/db", "records": []},
    )

    with pytest.raises(ValueError, match="execution_receipt"):
        load_receipt(proposal, "cluster/db")


def test_receipt_is_bound_to_database_fingerprint(tmp_path):
    from scripts.backfill_conversation_ownership import load_receipt, write_document

    receipt = tmp_path / "receipt.json"
    write_document(
        receipt,
        {"version": 1, "kind": "execution_receipt", "database": "cluster-a/db", "records": []},
    )

    with pytest.raises(ValueError, match="different database"):
        load_receipt(receipt, "cluster-b/db")


def test_receipt_requires_committed_run_attestation(tmp_path):
    from scripts.backfill_conversation_ownership import load_receipt, write_document

    receipt = tmp_path / "receipt.json"
    write_document(
        receipt,
        {
            "version": 1,
            "kind": "execution_receipt",
            "database": "cluster/db",
            "records": [],
        },
    )

    with pytest.raises(ValueError, match="committed receipt"):
        load_receipt(receipt, "cluster/db")


@pytest.mark.asyncio
async def test_receipt_is_published_only_after_database_commit(tmp_path):
    from scripts.backfill_conversation_ownership import commit_write

    events = []
    connection = AsyncMock()
    connection.execute.side_effect = [MagicMock(rowcount=1), MagicMock(rowcount=1)]
    transaction = AsyncMock()
    transaction.commit.side_effect = lambda: events.append("commit")
    receipt = tmp_path / "receipt.json"

    await commit_write(
        connection=connection,
        transaction=transaction,
        records=[
            {
                "conversation_id": "conv-1",
                "tenant_id": "tenant-a",
                "user_id": "alice",
                "api_key_id": "key-a",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        database="cluster/db",
        proposal_sha256="a" * 64,
        receipt_path=receipt,
        on_receipt=lambda: events.append("receipt"),
    )

    assert events == ["commit", "receipt"]


def test_recovery_document_requires_matching_applied_audit():
    from scripts.backfill_conversation_ownership import build_recovery_receipt, records_sha256

    records = [{"conversation_id": "conv-1"}]
    digest = records_sha256(records)
    audit = {
        "status": "applied",
        "proposal_sha256": "a" * 64,
        "records_sha256": digest,
        "count": 1,
    }
    receipt = build_recovery_receipt(
        run_id="run-1",
        database="cluster/db",
        proposal_sha256="a" * 64,
        records=records,
        audit=audit,
    )
    assert receipt["status"] == "committed"
    assert receipt["run_id"] == "run-1"

    with pytest.raises(ValueError, match="audit"):
        build_recovery_receipt(
            run_id="run-1",
            database="cluster/db",
            proposal_sha256="a" * 64,
            records=records,
            audit=dict(audit, count=2),
        )


@pytest.mark.asyncio
async def test_updates_are_counted_per_row_when_driver_batch_count_is_unknown():
    from scripts.backfill_conversation_ownership import apply_records

    connection = AsyncMock()
    first = MagicMock(rowcount=1)
    second = MagicMock(rowcount=1)
    connection.execute.side_effect = [first, second]

    matched = await apply_records(
        connection,
        "UPDATE example SET owner = :owner WHERE id = :id",
        [{"id": "one", "owner": "key"}, {"id": "two", "owner": "key"}],
    )

    assert matched == 2
    assert connection.execute.await_count == 2
