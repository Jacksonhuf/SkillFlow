from __future__ import annotations

import re

from browser_skill.models import AuthSpec, AuthState, BrowserSnapshot, SignalSpec


class AuthClassifier:
    def classify(self, spec: AuthSpec, snapshot: BrowserSnapshot) -> AuthState:
        authenticated = any(self._matches(signal, snapshot) for signal in spec.login_check.any)
        unauthenticated = any(
            self._matches(signal, snapshot) for signal in spec.unauthenticated_signals
        )
        if authenticated and not unauthenticated:
            return AuthState.AUTHENTICATED
        if unauthenticated and not authenticated:
            return AuthState.UNAUTHENTICATED
        return AuthState.UNKNOWN

    @staticmethod
    def _matches(signal: SignalSpec, snapshot: BrowserSnapshot) -> bool:
        if signal.url_contains is not None:
            return signal.url_contains.casefold() in snapshot.url.casefold()
        needle = (signal.semantic_element or "").casefold()
        tokens = {
            token for token in re.split(r"[\s,，。;；:：|/\\]+", snapshot.text.casefold()) if token
        }
        if needle in tokens:
            return True
        return any(
            needle in str(value).casefold()
            for element in snapshot.elements
            for value in element.values()
        )
