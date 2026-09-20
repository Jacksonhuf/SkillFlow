from browser_skill.models import AuthState, BrowserSnapshot
from browser_skill.runtime.auth import AuthClassifier


def test_auth_classifies_authenticated(template) -> None:
    snapshot = BrowserSnapshot(url="https://example.internal/home", text="欢迎 退出登录")
    assert AuthClassifier().classify(template.auth, snapshot) == AuthState.AUTHENTICATED


def test_auth_conflicting_signals_are_unknown(template) -> None:
    snapshot = BrowserSnapshot(url="https://example.internal/home", text="退出登录 用户名 登录")
    assert AuthClassifier().classify(template.auth, snapshot) == AuthState.UNKNOWN
