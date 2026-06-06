# Skill-Writing Techniques (the "Farzapedia" craft)

> **Thesis:** A good skill/spec is **MECE yet readable**. MECE usually means exhaustive (long, dry);
> readable means short. You resolve the tension with three compressions — tables, named handles,
> and shown examples — not by writing more prose.

Distilled from Farza's `wiki` skill ([gist](https://gist.github.com/farzaa/c35ac0cfbeb957788650e36aabea836d)),
proven on `docs/superpowers/specs/2026-06-06-bebop-assistant-design.md`. Apply this whenever **we
author or revise a skill or a spec.**

---

## The core tension

| Force | Pulls toward | Failure mode if it wins alone |
|---|---|---|
| MECE (mutually exclusive, collectively exhaustive) | completeness | a long, dry, unread wall |
| Readable | brevity | gaps, overlap, hand-waving |

The craft is making *one* artifact do both. Every technique below is a compression that buys
exhaustiveness without paying in length.

---

## The techniques

| # | Technique | What it is | Why it works | When |
|---|---|---|---|---|
| 1 | **Sets → tables** | Any set of categories becomes a table (rows = cases, columns = fixed dimensions). | A table *forces* MECE — overlap and gaps become visible. Scannable, not linear. | Always, for any list of ≥3 parallel things. |
| 2 | **Named handles** | Elevate load-bearing rules to sticky labels: *Anti-Cramming, the Steve Jobs test, Delta-only, Fail loud.* | A label compresses a rule into something you can hold and point at. Re-derivable from the handle. | Always, for the 4–8 rules the design rests on. |
| 3 | **Show, don't tell (Bad/Good)** | A concrete Bad vs Good example side by side. | One glance conveys what a paragraph of adjectives can't. Defines the bar by demonstration. | Whenever quality is judged on taste/signal. |
| 4 | **One-line thesis up top** | A single sentence the whole doc hangs off; restate the frame as an anchor. | Reader gets the gestalt before the depth; every section is checkable against it. | Always. |
| 5 | **IS / IS-NOT** | State goals *and* non-goals; pair every "do" with a "don't." | Defining the negative space is itself a MECE discipline — boundaries stop scope creep. | Always. |
| 6 | **Verb-spine + parallel anatomy** | Organize around the user's commands; give each the *same* internal shape (purpose → phases → rules). | Once you've read one section you can skim the rest. The commands are the MECE backbone. | **Multi-command skills only.** |
| 7 | **Imperative, one-claim sentences** | Short declaratives. "You are a writer. Not a clerk." | Density without fog. The doc practices its own tone rules. | Always. |
| 8 | **Principles recap** | A short numbered list of the non-negotiables, as bookend. | Memorable close; the handles in one place. | Skills; optional for specs (the Invariants table can serve). |

---

## Applicability (don't cargo-cult)

| Technique | Skill (operating manual) | Spec (single-decision record) |
|---|---|---|
| 1 Tables, 2 Handles, 3 Bad/Good, 4 Thesis, 5 IS/IS-NOT, 7 Imperative | ✅ | ✅ |
| 6 Verb-spine + parallel anatomy | ✅ core | ❌ no repeating unit — skip |
| 8 Principles recap | ✅ | optional (Invariants table) |

The two techniques that make Farza's *skill* shine (6, 8) are for a multi-command manual. A spec has
one decision, not a verb set — forcing a command-spine onto it is copying the form without the
function. Match the technique to the genre.

---

## Show, don't tell (the technique, on itself)

**Bad** — a rule buried in prose (real failure mode):
> The runner should be careful to only move its saved timestamp forward after the message has
> actually been sent, because otherwise if a run fails you might end up skipping some emails.

**Good** — the same rule as a named handle, stated once, referenced everywhere:
> **Advance only on success** — `state.json` moves forward *only* after `SENT`. A failed run
> re-scans the same window; it never skips email.

The handle is shorter, unambiguous, and every error-handling row can just tag `[Advance-on-success]`
instead of re-explaining.

---

## Pre-ship checklist

Run before declaring a skill or spec done:

1. Is there a **one-line thesis** at the top? Does every section serve it?
2. Is every **set of ≥3 categories a table**, not a prose list?
3. Are the **load-bearing rules named handles**, used consistently?
4. Is there a **Bad/Good example** wherever quality is a judgment call?
5. Are **non-goals** stated as explicitly as goals?
6. (Skill) Is it organized around the user's **verbs**, each with the **same anatomy**?
7. (Skill) Is there a **Principles** recap?
8. Did you **skip** the techniques that don't fit the genre, on purpose?
9. Does the prose itself obey **one-claim-per-sentence**? Cut the rest.
