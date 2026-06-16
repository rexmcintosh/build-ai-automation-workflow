import textwrap

MEMBER_OUTPUT = textwrap.dedent("""\
    Respond with ONLY a JSON object (no markdown, no prose around it):
    {
      "stance": "approve | concerns | oppose | na",
      "headline": "one sentence",
      "findings": [
        {"point": "short; include file:line for code", "severity": "info|low|med|high|critical", "confidence": 1-10}
      ],
      "suggestions": ["short optional improvements"]
    }
    confidence is YOUR certainty the finding is real (10 = certain). Keep lists <= 6 items.
    You are NOT here to rubber-stamp. Take a position.
""")

SYNTH_OUTPUT = textwrap.dedent("""\
    You are the CHAIR of a council. You have read every panelist's answer (they
    answered independently, blind to each other). Respond with ONLY a JSON object:
    {
      "recommendation": "the council's consensus answer / verdict",
      "confidence": 1-10,
      "consensus": ["points two or more panelists raised independently"],
      "disagreements": [
        {"topic":"...", "type":"mechanical|taste|user-challenge",
         "positions":"who held what", "resolution":"your call (mechanical/taste)",
         "what_we_might_miss":"(user-challenge only)", "if_wrong_cost":"(user-challenge only)"}
      ],
      "cross_panel_themes": ["concerns appearing across multiple lenses"]
    }
    Classify each disagreement: mechanical = one right answer (resolve it silently in
    recommendation); taste = valid differences (recommend, but list it); user-challenge =
    the panel agrees the user's stated direction is wrong (never silent; fill
    what_we_might_miss + if_wrong_cost; the user's direction is the default).
""")

COMPARE_OUTPUT = textwrap.dedent("""\
    You are comparing several CANDIDATE solutions to the SAME task. They were
    produced independently. Judge them on your lens; do not rubber-stamp.
    Respond with ONLY a JSON object (no markdown, no prose around it):
    {
      "pick": "<label of the single best candidate>",
      "ranking": ["<labels, best to worst>"],
      "rationale": "one tight paragraph: why the pick wins and the runners-up lose"
    }
    Use the exact candidate labels you were given. Pick exactly one winner.
""")

COMPARE_SYNTH = textwrap.dedent("""\
    You are the CHAIR. Panelists independently ranked several candidate solutions
    to the same task (they were blind to each other). Pick the council's winner and
    say what to salvage from the losers. Respond with ONLY a JSON object:
    {
      "winner": "<label of the winning candidate>",
      "confidence": 1-10,
      "ranking": ["<labels, best to worst>"],
      "rationale": "why this candidate wins overall, accounting for the panel",
      "grafts": ["specific good ideas worth taking from the runners-up"]
    }
    Use the exact candidate labels. If panelists disagree, weigh their reasoning, not
    just their votes. The winner must be one of the actual candidate labels.
""")

ROUTER_PROMPT = textwrap.dedent("""\
    Pick the single best panel for the user's input. Respond with ONLY:
    {"panel": "<one of the names below>"}
    Panels:
""")
