"""fixit — the feedback -> fix -> ship loop.

An inbound issue is claimed from a file-based queue, handed to a constrained
headless agent that writes a minimal fix on a fresh branch and opens a PR, which
the existing GitHub Actions council review gates. The human merges. The agent never
touches `main` and never merges. See
docs/superpowers/specs/2026-06-16-industrial-features-design.md.
"""
