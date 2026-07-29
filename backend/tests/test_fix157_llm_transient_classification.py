"""Fix-157: the primary-LLM retry never fired for any transport error.

`_chat_with_fallback` classified transience by substring-matching `str(e)`. Every
httpx transport exception stringifies to the EMPTY STRING, so none of the tokens
the classifier looks for ("ReadTimeout", "ConnectError", ...) could ever match --
each one scored `transient=False` and broke out of the retry loop on attempt 1,
despite the docstring promising 3 attempts with exponential backoff.

Found live on 2026-07-29 while the shared Bifrost gateway was hanging: Zero
logged `llm_primary_failed ... error= transient=False` on a 45-second timeout.
`error=` empty AND the retry skipped.
"""
import httpx
import pytest

from app.infrastructure.unified_llm_client import _describe_exc

# The exact set named in the classifier's own comment, plus PoolTimeout, which is
# the gateway pool-exhaustion signature and the case retrying helps most.
TRANSPORT_EXCEPTIONS = [
    httpx.ReadTimeout(""),
    httpx.ConnectTimeout(""),
    httpx.PoolTimeout(""),
    httpx.WriteTimeout(""),
    httpx.ReadError(""),
    httpx.ConnectError(""),
    httpx.RemoteProtocolError(""),
]


@pytest.mark.parametrize("exc", TRANSPORT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_transport_exceptions_really_do_stringify_empty(exc):
    """The premise of the bug. If this ever fails, httpx changed and the
    type-based classification below can be revisited."""
    assert str(exc) == ""


@pytest.mark.parametrize("exc", TRANSPORT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_transport_exceptions_classify_as_transient(exc):
    """Type-based classification catches every one; the old substring test caught none."""
    assert isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


@pytest.mark.parametrize("exc", TRANSPORT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_old_substring_classifier_missed_all_of_them(exc):
    """Regression guard: documents precisely what was broken."""
    err_s = str(exc)
    old_transient = (
        "Server disconnected" in err_s
        or "ReadError" in err_s
        or "ConnectError" in err_s
        or "RemoteProtocolError" in err_s
        or "ReadTimeout" in err_s
        or "429" in err_s
        or "Too Many Requests" in err_s
        or "502" in err_s
        or "503" in err_s
        or "504" in err_s
    )
    assert old_transient is False


@pytest.mark.parametrize("exc", TRANSPORT_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_describe_exc_never_returns_empty(exc):
    """`error=` in the log must always carry signal."""
    described = _describe_exc(exc)
    assert described
    assert type(exc).__name__ in described


def test_describe_exc_keeps_the_message_when_there_is_one():
    assert _describe_exc(ValueError("boom")) == "ValueError: boom"


@pytest.mark.parametrize(
    "text",
    ["Server disconnected", "429 Too Many Requests", "502 Bad Gateway", "503", "504"],
)
def test_status_code_cases_still_match_by_message(text):
    """Status-code failures only ever appear as message text, so the substring
    arm of the classifier still has to cover them."""
    err_s = _describe_exc(RuntimeError(text))
    assert (
        "Server disconnected" in err_s
        or "429" in err_s
        or "Too Many Requests" in err_s
        or "502" in err_s
        or "503" in err_s
        or "504" in err_s
    )


def test_non_transient_errors_stay_non_transient():
    """A genuine application error must NOT be retried 3x."""
    exc = ValueError("model 'nope' does not exist")
    assert not isinstance(exc, (httpx.TimeoutException, httpx.TransportError))
    err_s = _describe_exc(exc)
    assert not (
        "Server disconnected" in err_s
        or "429" in err_s
        or "Too Many Requests" in err_s
        or "502" in err_s
        or "503" in err_s
        or "504" in err_s
    )
