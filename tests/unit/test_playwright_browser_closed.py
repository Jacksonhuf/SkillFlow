from browser_skill.browser.playwright_adapter import looks_like_browser_closed


def test_looks_like_browser_closed_matches_playwright_message() -> None:
    exc = RuntimeError(
        "BrowserContext.new_page: Target page, context or browser has been closed"
    )
    assert looks_like_browser_closed(exc) is True


def test_looks_like_browser_closed_ignores_unrelated() -> None:
    assert looks_like_browser_closed(TimeoutError("timeout")) is False
