"""Mesh watchdog — autonomous SRE for the automated system's own moving parts.

Pure-function triage core (`triage.py`) over signals collected by the shell
runner (`run-watchdog.sh`). The watchdog *diagnoses and proposes*; it never
touches production. See docs/superpowers/specs/2026-06-16-industrial-features-design.md.
"""
