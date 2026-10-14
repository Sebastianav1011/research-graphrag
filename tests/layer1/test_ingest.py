import pytest
from layer1_data.ingest import ingest


def load(path, settings, **spec):
    return ingest(path, "proyectos", {"type": "csv", **spec}, settings, "test")


def test_valid_multiline_and_physical_line(tmp_path, settings):
    path = tmp_path / "valid.csv"
    path.write_text('id,title\n1,"long\ntext"\n2,Other\n', encoding="utf-8")
    rows, events, meta = load(path, settings)
    assert not events
    assert [r["_row"] for r in rows] == [2, 4]
    assert rows[0]["title"].replace("\r\n", "\n") == "long\ntext"
    assert meta["records_read"] == 2 and len(meta["sha256"]) == 64


def test_missing_file(tmp_path, settings):
    assert load(tmp_path / "missing.csv", settings)[1][0]["anomaly_code"] == "FILE_NOT_FOUND"


@pytest.mark.parametrize("content", [b"", b"  \n ", b"id,title\n"])
def test_empty_file(tmp_path, settings, content):
    p = tmp_path / "empty.csv"
    p.write_bytes(content)
    assert any(e["anomaly_code"] == "EMPTY_FILE" for e in load(p, settings)[1])


def test_encoding_fallback(tmp_path, settings):
    p = tmp_path / "latin.csv"
    p.write_bytes("id,titulo\n1,Investigación\n".encode("cp1252"))
    rows, events, meta = load(p, settings)
    assert rows[0]["titulo"] == "Investigación"
    assert meta["encoding"] == "cp1252"
    assert events[0]["anomaly_code"] == "ENCODING_FALLBACK"


def test_invalid_encoding(tmp_path, settings):
    p = tmp_path / "bad.csv"
    p.write_bytes(b"id,title\n1,\xff\xfe")
    assert load(p, settings, encoding="utf-8")[1][0]["anomaly_code"] == "INVALID_ENCODING"


@pytest.mark.parametrize("content,options,code", [
    ("id;title\n1;Hello\n", {"delimiter": ","}, "INVALID_DELIMITER"),
    ("ID,id\n1,2\n", {}, "DUPLICATE_HEADER"),
    ("id,title\n1,hello,extra\n", {}, "INVALID_COLUMN_COUNT"),
    ('id,title\n1,"broken\n', {}, "MALFORMED_ROW"),
    ("id,title\n,\n", {}, "EMPTY_RECORD"),
])
def test_structural_anomalies(tmp_path, settings, content, options, code):
    p = tmp_path / "bad.csv"
    p.write_text(content, encoding="utf-8")
    assert code in {e["anomaly_code"] for e in load(p, settings, **options)[1]}


def test_raw_never_modified(tmp_path, settings):
    p = tmp_path / "raw.csv"
    data = b"id,title\n1,  Test  \n"
    p.write_bytes(data)
    load(p, settings)
    assert p.read_bytes() == data
