"""Secrets out of text that leaves this Mac. The corpus itself keeps everything (decided 2026-10-09: fine as long as
it stays local); this is applied only where text is handed to a model, e.g. the ask-my-data app's tools, so a note
holding an API key or a wallet's recovery phrase can't be sent to Anthropic or OpenAI with a search result.

    redact(text) -> text with each secret replaced by [redacted <kind>]

What counts: private keys, API keys and tokens with a known shape (OpenAI, Anthropic, OpenRouter, GitHub, Slack,
Google, AWS, Stripe), JWTs and bearer tokens, password/passcode values, secret-looking URL parameters, card numbers
(Luhn-valid, with a network prefix) and wallet recovery phrases (12 or more words in a row from the BIP39 list in
data/bip39_english.txt, from trezor/python-mnemonic, MIT).
"""

import re
from pathlib import Path

WORDS = frozenset((Path(__file__).with_name("data") / "bip39_english.txt").read_text().split())

_VALUE = r"(?:\"[^\"]*\"|'[^']*'|[^\s\"',;&]+)"
# (kind, pattern): a match's "keep" group (a label like "password: ") stays; the rest becomes [redacted kind].
PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----[\s\S]{0,8000}?(?:-----END (?:[A-Z]+ )*PRIVATE KEY-----|$)")),
    ("private key", re.compile(r"(?P<keep>\"private_key\":\s*\")[^\"]{20,}")),
    ("API key", re.compile(r"\bsk-(?:ant-|proj-|or-v1-)?[A-Za-z0-9_-]{20,}")),
    ("token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[abprs]-[A-Za-z0-9-]{10,})")),
    ("API key", re.compile(r"\b(?:AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|(?:sk|rk)_live_[A-Za-z0-9]{16,})")),
    ("token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("token", re.compile(r"(?i)(?P<keep>\bbearer\s+)[A-Za-z0-9._~+/=-]{16,}")),
    ("password", re.compile(rf"(?i)(?P<keep>\b(?:password|passwd|passcode|pwd)(?:\s*[:=]\s*|\s+is\s+)){_VALUE}")),
    ("secret", re.compile(rf"(?i)(?P<keep>\b(?:aws_secret_access_key|client_secret|secret_key|api_key|apikey|access_token|"
                          rf"refresh_token|token_secret|token-secret)\s*[=:]?\s*){_VALUE}")),
    ("secret", re.compile(r"(?i)(?P<keep>[?&](?:token|access_token|refresh_token|id_token|auth|api_key|apikey|key|password|sig|"
                          r"signature|code|otp)=)[A-Za-z0-9%._~+/=-]{12,}")),
]
CARD = re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)(?:[ -]?\d{4}){2}[ -]?\d{1,4}\b")
# A card number is only one when the text around it talks about a card (order and tracking numbers pass Luhn too).
CARD_WORDS = re.compile(r"(?i)\b(?:card|visa|mastercard|master card|amex|american express|discover|credit|debit|cvc|cvv|"
                        r"security code|exp(?:iry|iration|ires)?|valid thru)\b")
WORD = re.compile(r"[a-z]+")


def _luhn(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        total, alt = total + n, not alt
    return total % 10 == 0


def _seed_phrases(text):
    """Spans of 12 or more BIP39 words in a row (separated by spaces, commas, numbers or line breaks), mostly
    different words: a real phrase rarely repeats one, while "zoo zoo zoo..." in a chat isn't a phrase."""
    spans, run = [], []

    def close():
        words = [m.group(0) for m in run]
        if len(words) >= 12 and len(set(words)) >= max(9, int(len(words) * 0.75)):
            spans.append((run[0].start(), run[-1].end()))

    for m in WORD.finditer(text):
        if run and not re.fullmatch(r"[\s,.;:\d)]*", text[run[-1].end():m.start()]):
            close()
            run = []
        if m.group(0) in WORDS:
            run.append(m)
        else:
            close()
            run = []
    close()
    return spans


def redact(text):
    if not text:
        return text
    for start, end in reversed(_seed_phrases(text)):
        text = text[:start] + "[redacted recovery phrase]" + text[end:]
    for kind, pat in PATTERNS:
        text = pat.sub(lambda m, k=kind: (m.groupdict().get("keep") or "") + f"[redacted {k}]", text)
    def card(m):
        around = text[max(0, m.start() - 60):m.end() + 60]
        return "[redacted card number]" if _luhn(re.sub(r"\D", "", m.group(0))) and CARD_WORDS.search(around) else m.group(0)
    return CARD.sub(card, text)


class RedactingStream:
    """Wraps a text stream (stdout): every line written is redacted first."""

    def __init__(self, stream):
        self.stream, self.buf = stream, ""

    def write(self, s):
        self.buf += s
        *lines, self.buf = self.buf.split("\n")
        for line in lines:
            self.stream.write(redact(line) + "\n")
        return len(s)

    def flush(self):
        if self.buf:
            self.stream.write(redact(self.buf))
            self.buf = ""
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def install_if_asked():
    """Redact everything this process prints when ASK_ME_REDACT=1 (set by the ask-my-data app for its agent)."""
    import atexit
    import os
    import sys
    if os.environ.get("ASK_ME_REDACT") == "1" and not isinstance(sys.stdout, RedactingStream):
        sys.stdout = RedactingStream(sys.stdout)
        atexit.register(sys.stdout.flush)
