"""アクセス制御ロジック（ドメイン制限・管理者判定）のテスト。"""
import pytest

from config import settings


@pytest.fixture
def domains(monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", ["life-time-support.com"])
    monkeypatch.setattr(settings, "ADMIN_EMAILS", ["planner@life-time-support.com"])


@pytest.mark.usefixtures("domains")
class TestAccessControl:
    def test_allowed_domain(self):
        assert settings.is_allowed_domain("taro@life-time-support.com")

    def test_allowed_domain_case_insensitive(self):
        assert settings.is_allowed_domain("Taro@Life-Time-Support.com")

    def test_disallowed_domain(self):
        assert not settings.is_allowed_domain("taro@gmail.com")

    @pytest.mark.parametrize("bad", ["", None, "no-at-mark", "@nodomain"])
    def test_malformed_emails(self, bad):
        assert not settings.is_allowed_domain(bad)

    def test_is_admin(self):
        assert settings.is_admin("planner@life-time-support.com")
        assert not settings.is_admin("other@life-time-support.com")
        assert not settings.is_admin(None)


def test_criteria_are_five_and_unique_keys():
    assert len(settings.EVALUATION_CRITERIA) == 5
    keys = [c.key for c in settings.EVALUATION_CRITERIA]
    assert len(set(keys)) == 5
    assert set(settings.CRITERIA_BY_KEY) == set(keys)
