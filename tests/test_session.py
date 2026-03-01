import pytest

from pravni_kvalifikator.web.session import SessionDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_sessions.db"
    db = SessionDB(db_path)
    db.create_tables()
    return db


def test_create_tables(db):
    with db._conn() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row["name"] for row in cursor.fetchall()]
    assert "sessions" in tables
    assert "qualifications" in tables
    assert "agent_log" in tables


def test_create_session(db):
    session_id = db.create_session()
    assert session_id is not None
    assert len(session_id) == 36  # UUID v4 format


def test_get_session(db):
    sid = db.create_session()
    session = db.get_session(sid)
    assert session is not None
    assert session["id"] == sid


def test_create_qualification(db):
    sid = db.create_session()
    qid = db.create_qualification(sid, "Někdo ukradl kolo", "TC")
    assert qid > 0

    qual = db.get_qualification(qid)
    assert qual["popis_skutku"] == "Někdo ukradl kolo"
    assert qual["typ"] == "TC"
    assert qual["stav"] == "pending"


def test_update_qualification_status(db):
    sid = db.create_session()
    qid = db.create_qualification(sid, "test", "TC")

    db.update_qualification(qid, stav="completed", vysledek='{"test": true}')
    qual = db.get_qualification(qid)
    assert qual["stav"] == "completed"
    assert qual["vysledek"] == '{"test": true}'


def test_insert_agent_log(db):
    sid = db.create_session()
    qid = db.create_qualification(sid, "test", "TC")

    db.insert_agent_log(qid, "head_classifier", "started", "Začínám klasifikaci")
    db.insert_agent_log(qid, "head_classifier", "completed", "Hotovo", {"chapters": [1, 2]})

    logs = db.get_agent_logs(qid)
    assert len(logs) == 2
    assert logs[0]["agent_name"] == "head_classifier"
    assert logs[0]["stav"] == "started"


def test_list_qualifications_by_session(db):
    sid = db.create_session()
    db.create_qualification(sid, "skutek 1", "TC")
    db.create_qualification(sid, "skutek 2", "PR")

    quals = db.list_qualifications(sid)
    assert len(quals) == 2
