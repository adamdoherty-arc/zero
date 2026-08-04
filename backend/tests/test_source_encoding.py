"""
Guard against double-encoded (mojibake) text re-entering the source tree.

On 2026-08-04 a repo scan found 556 occurrences across 25 committed files: UTF-8
bytes that had been decoded as cp1252 and re-encoded as UTF-8, so an em dash was
stored as a three-character run and whole box-drawing diagrams became noise. It
was not cosmetic. `scheduler_service._run_meal_daily_digest` builds its markdown
from string literals, so the corrupt em dash was rendered verbatim into the vault
note that job writes every morning, and the vault indexer faithfully embedded it.

The signature is unambiguous: a cp1252 high-byte lead (0xC2/0xC3/0xE2) followed
by more non-ASCII, where encoding the run back to cp1252 yields valid UTF-8.
Anything matching that is corruption, never intended text.

Every character this module needs to talk about is built with chr(); a literal
would make the guard fail on its own fixture.
"""

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Retired code and vendored trees are excluded: they are unmaintained, and
# rewriting them is exactly the churn TaskExecutionService was fenced out of.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "_archive", "attic", ".archive", "dist", "build", ".mypy_cache",
    ".pytest_cache", ".ruff_cache",
}

SOURCE_GLOBS = ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx")

LEADS = chr(0xC2) + chr(0xC3) + chr(0xE2)
MOJIBAKE = re.compile("[" + LEADS + "][^\\x00-\\x7f]{1,2}")


def _is_mojibake(run: str) -> bool:
    """True when the run round-trips cp1252 -> UTF-8 into a single real char."""
    try:
        decoded = run.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    return len(decoded) == 1 and ord(decoded) > 127


def _source_files():
    for glob in SOURCE_GLOBS:
        for path in REPO_ROOT.rglob(glob):
            if SKIP_DIRS & set(path.parts):
                continue
            yield path


def test_no_double_encoded_text_in_source():
    offenders = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = [m.group(0) for m in MOJIBAKE.finditer(text) if _is_mojibake(m.group(0))]
        if hits:
            rel = path.relative_to(REPO_ROOT).as_posix()
            sample = " ".join("U+%04X" % ord(c) for c in hits[0])
            offenders.append(f"{rel}: {len(hits)} occurrence(s), first=[{sample}]")

    assert not offenders, (
        "Double-encoded text found. These are UTF-8 bytes that were read as cp1252 "
        "and re-encoded; repair each run with run.encode('cp1252').decode('utf-8'):\n  "
        + "\n  ".join(offenders)
    )


def test_detector_recognises_a_known_mojibake_run():
    """Pin the detector itself so a broken regex cannot silently pass the guard."""
    # What U+2014 (em dash) becomes after the cp1252 round trip.
    corrupt = chr(0xE2) + chr(0x20AC) + chr(0x201D)
    assert MOJIBAKE.fullmatch(corrupt)
    assert _is_mojibake(corrupt)
    assert corrupt.encode("cp1252").decode("utf-8") == chr(0x2014)


@pytest.mark.parametrize(
    "text",
    [
        "plain ascii",
        "em dash " + chr(0x2014) + " here",
        "arrow " + chr(0x2192) + " there",
        "caf" + chr(0xE9),
        "box " + chr(0x251C) + chr(0x2500) + chr(0x2500),
    ],
)
def test_detector_does_not_flag_correct_text(text):
    assert not [m for m in MOJIBAKE.finditer(text) if _is_mojibake(m.group(0))]
