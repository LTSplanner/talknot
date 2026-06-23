"""google_drive.list_videos の絞り込み（自分所有のみ）をテストする。

ネットワークは使わず、Drive サービスをフェイクに差し替えて
list() に渡るクエリ・パラメータを検証する。
"""
from services import google_drive


class _FakeList:
    def __init__(self, captured: dict, kwargs: dict):
        captured["kwargs"] = kwargs

    def execute(self):
        return {"files": []}


class _FakeFiles:
    def __init__(self, captured):
        self._captured = captured

    def list(self, **kwargs):
        return _FakeList(self._captured, kwargs)


class _FakeService:
    def __init__(self, captured):
        self._captured = captured

    def files(self):
        return _FakeFiles(self._captured)


def _patch(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(google_drive, "_service", lambda creds: _FakeService(captured))
    return captured


def test_owned_only_restricts_to_self(monkeypatch):
    captured = _patch(monkeypatch)
    google_drive.list_videos("creds", owned_only=True)
    kw = captured["kwargs"]
    assert "'me' in owners" in kw["q"]          # 本人所有に限定
    assert kw["corpora"] == "user"              # 共有ドライブは見ない
    assert kw["includeItemsFromAllDrives"] is False


def test_default_lists_all_drives(monkeypatch):
    captured = _patch(monkeypatch)
    google_drive.list_videos("creds")
    kw = captured["kwargs"]
    assert "'me' in owners" not in kw["q"]
    assert kw["corpora"] == "allDrives"
    assert kw["includeItemsFromAllDrives"] is True


def test_name_filter_and_owned_combine(monkeypatch):
    captured = _patch(monkeypatch)
    google_drive.list_videos("creds", name_contains="商談", owned_only=True)
    q = captured["kwargs"]["q"]
    assert "name contains '商談'" in q and "'me' in owners" in q
