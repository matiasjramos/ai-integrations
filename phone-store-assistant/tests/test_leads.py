from datetime import timezone

from phone_store_assistant.leads import SqliteLeadRepository
from phone_store_assistant.models import Lead


def _lead(name="Ana"):
    return Lead(name, "ana@example.com", "SAM-A15-128", "Wants to buy this week")


def test_save_sets_id_and_utc_timestamp():
    repo = SqliteLeadRepository(":memory:")
    saved = repo.save(_lead())
    assert saved.id == 1
    assert saved.created_at.tzinfo == timezone.utc


def test_list_recent_newest_first_and_limit():
    repo = SqliteLeadRepository(":memory:")
    for n in ("a", "b", "c"):
        repo.save(_lead(n))
    assert [lead.name for lead in repo.list_recent(limit=2)] == ["c", "b"]


def test_persists_to_file(tmp_path):
    db = str(tmp_path / "leads.db")
    SqliteLeadRepository(db).save(_lead())
    [lead] = SqliteLeadRepository(db).list_recent()
    assert lead.contact == "ana@example.com"


def test_sql_injection_stored_as_data():
    repo = SqliteLeadRepository(":memory:")
    evil = "x'); DROP TABLE leads;--"
    repo.save(_lead(evil))
    assert repo.list_recent()[0].name == evil
