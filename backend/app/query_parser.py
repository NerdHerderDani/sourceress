import re
from dataclasses import dataclass

@dataclass
class ParsedQuery:
    must: list[str]
    should: list[str]
    must_not: list[str]

_token_re = re.compile(r'"([^"]+)"|(\S+)')

def tokenize(q: str) -> list[str]:
    out: list[str] = []
    for m in _token_re.finditer(q.strip()):
        phrase, word = m.group(1), m.group(2)
        out.append(phrase if phrase is not None else word)
    return out

def parse_boolean(q: str) -> ParsedQuery:
    # MVP: supports AND/OR/NOT, quotes; no parentheses.
    tokens = tokenize(q)
    must: list[str] = []
    should: list[str] = []
    must_not: list[str] = []

    mode = "MUST"  # MUST or SHOULD
    negate = False

    i = 0
    while i < len(tokens):
        t = tokens[i]
        upper = t.upper()
        if upper == "AND":
            mode = "MUST"
            i += 1
            continue
        if upper == "OR":
            mode = "SHOULD"
            i += 1
            continue
        if upper == "NOT":
            negate = True
            i += 1
            continue

        term = t
        if negate:
            must_not.append(term)
            negate = False
        else:
            (must if mode == "MUST" else should).append(term)
        i += 1

    # If only SHOULD terms were provided, treat them as MUST (avoid empty AND query)
    if not must and should:
        must, should = should, []

    return ParsedQuery(must=must, should=should, must_not=must_not)

def to_github_tokens(pq: ParsedQuery) -> list[str]:
    # GitHub search is basically AND with negation. We'll include MUST, exclude MUST_NOT.
    # SHOULD terms are appended too (approx), but we keep them later for scoring.
    toks: list[str] = []
    toks.extend(pq.must)
    toks.extend([f"-{t}" for t in pq.must_not])
    return toks
