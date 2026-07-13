# Quarantined 2026-07-13 (Enhancement-121 session)

Untracked artifacts found in backend/ that reference a Flask + flask_sqlalchemy
`zero` package which has never been part of this repo (Zero is FastAPI + async
SQLAlchemy). Almost certainly produced by an autonomous run (Fix-143 era)
writing against a hallucinated project layout. The four test_*.py files import
`from zero.dependencies ...` and broke pytest collection for the whole suite.
Kept here rather than deleted in case any intent needs salvaging.
