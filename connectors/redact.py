"""Secrets out of text that leaves this Mac. The corpus itself keeps everything (decided 2026-10-09: fine as long as
it stays local); this is applied only where text is handed to a model, e.g. the ask-my-data app's tools, so a note
holding an API key or a wallet's recovery phrase can't be sent to Anthropic or OpenAI with a search result.

    redact(text) -> text with each secret replaced by [redacted <kind>]

What counts: private keys, API keys and tokens with a known shape (OpenAI, Anthropic, OpenRouter, GitHub, GitLab,
Slack, Google, AWS, Stripe, npm, Hugging Face, SendGrid), JWTs and bearer tokens, password/passcode values (also
"the password for X is", PGPASSWORD= and the like, and the password in a link), secret-looking URL parameters, card
numbers (Luhn-valid, with a network prefix), Social Security numbers and bank account and routing numbers said as
such, a generated-looking password alone on its line (or after a short label like "Bank:") or with a symbol in a
sentence, and wallet recovery phrases (12 or more words in a row from the BIP39 list in data/bip39_english.txt, from
trezor/python-mnemonic, MIT).
"""

import re
from pathlib import Path

WORDS = frozenset((Path(__file__).with_name("data") / "bip39_english.txt").read_text().split())

_VALUE = r"(?:\"[^\"]*\"|'[^']*'|[^\s\"',;&]+)"
# (kind, pattern): a match's "keep" group (a label like "password: ") stays; the rest becomes [redacted kind].
PATTERNS = [
    # The key's lines, to its END line or the last line that looks like one (cut short, or followed by anything).
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----(?:\s*[A-Za-z0-9+/=]{8,}|\s*[A-Za-z-]+:[^\n]*)*\s*(?:-----END (?:[A-Z]+ )*PRIVATE KEY-----)?")),
    ("private key", re.compile(r"(?P<keep>\"private_key\":\s*\")[^\"]{20,}")),
    ("API key", re.compile(r"\bsk-(?:ant-|proj-|or-v1-)?[A-Za-z0-9_-]{20,}")),
    ("token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{20,}|"
                         r"npm_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}|ya29\.[A-Za-z0-9_-]{20,}|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})")),
    ("API key", re.compile(r"\b(?:AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|(?:sk|rk)_live_[A-Za-z0-9]{16,})")),
    ("token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("token", re.compile(r"(?i)(?P<keep>\bbearer\s+)[A-Za-z0-9._~+/=-]{16,}")),
    ("password", re.compile(rf"(?i)(?P<keep>\b(?:password|passwd|passcode|pwd)(?:\*\*|__)?(?:\s*[:=]\s*|\s+is\s+)){_VALUE}")),
    ("password", re.compile(rf"(?i)(?P<keep>\b(?:password|passwd|passcode|pin)\s+(?:for|to)\s+[^\s:=]{{1,40}}\s+(?:is\s+|[:=]\s*))(?!\[redacted){_VALUE}")),
    ("password", re.compile(rf"(?P<keep>\b[A-Z0-9_]*(?:PASSWORD|PASSWD|PASS|SECRET|TOKEN|API_KEY|APIKEY)[A-Z0-9_]*\s*=\s*)(?!\[redacted){_VALUE}")),
    ("password", re.compile(r"(?P<keep>\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@]{1,64}:)[^\s@/]{1,128}(?=@)")),
    ("secret", re.compile(rf"(?i)(?P<keep>\b(?:aws_secret_access_key|client_secret|secret_key|api_key|apikey|access_token|"
                          rf"refresh_token|token_secret|token-secret)\s*[=:]?\s*){_VALUE}")),
    ("secret", re.compile(r"(?i)(?P<keep>[?&](?:token|access_token|refresh_token|id_token|auth|api_key|apikey|key|password|sig|"
                          r"signature|code|otp|secret)=)[A-Za-z0-9%._~+/=-]{12,}")),
    ("Social Security number", re.compile(r"(?i)(?P<keep>\b(?:ssn|social security(?: number| no\.?)?|soc\. sec\.)\s*(?:#|number|no\.?)?(?:\s+is)?\s*[:#]?\s*)"
                                          r"(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b")),
    ("account number", re.compile(r"(?i)(?P<keep>\b(?:routing|aba|account|acct|iban)(?:\s*(?:number|no\.?|#))?\s*[:#]?\s*)[A-Z]{0,2}\d[\d ]{5,30}\d\b")),
]
CARD = re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|2(?:2[2-9]\d|[3-6]\d{2}|7[01]\d|720)|3[47]\d{2}|6011)(?:[ -]?\d{4}){2}[ -]?\d{1,4}\b")
# A card number is only one when the text around it talks about a card (order and tracking numbers pass Luhn too).
CARD_WORDS = re.compile(r"(?i)\b(?:card|visa|mastercard|master card|amex|american express|discover|credit|debit|cvc|cvv|"
                        r"security code|exp(?:iry|iration|ires)?|valid thru)\b")
WORD = re.compile(r"[a-z]+")
# A password saved in a note usually sits alone on its line, after a list or quote marker or a short label
# ("Bank: ...", "- email = ..."): one token of 10 to 40 characters that looks like a password (_password_like).
# What looks like that but isn't one: links, emails, paths, file names, IDs and hashes, dates, code, names made of words.
STANDALONE = re.compile(r"(?m)^(?P<keep>[ \t]*(?:(?:[-*+>]|\d{1,3}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?)*)(?P<rest>[^\n]*?)[ \t\r]*$")
LABELLED = re.compile(r"(?P<label>[^\s:=]{1,30}(?:[ \t][^\s:=]{1,30}){0,3}[ \t]*(?:[:=]|[ \t]-)[ \t]*)(?P<tok>\S{10,42})$")
QUOTED = re.compile(r"^([`'\"])(.+)\1$")
# Each one's name says what it keeps (a check can say which fired without showing the token).
NOT_A_PASSWORD_PARTS = {
    "link": r"^\[?(?i:(?:mailto|tel|sms|data|urn|cid|file|javascript|about|arxiv|doi|isbn|https?|ftp):|www\.)|://",
    "markup": r"^(?:\[|!\[|<|\||\(|-{2})|^\{.*\}$|\*\*|__|&#?\w+;",
    "tag or variable": r"^#[\w/-]+$|^@[\w.-]+$|^\$\{?\w+\}?$|^\$\{.*\}$",
    "email": r"[^@\s]+@[^@\s]+\.(?i:[a-z]{2,})$",
    "path": r"^[/~\\]|^\.\.?/|/.*/|^[A-Za-z]+/[A-Za-z]+$|\\",
    "file name": r"\.(?i:[a-z]{2,5}|[a-z]{1,3}\d)$",
    "hex or number": r"^[0-9a-f-]{8,}$|^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|^[0-9:.+-]+$|^v?\d+(?:\.\d+)+",
    "code": r"\(\)|[)\]]$|::|->|=>|(?i:!important)",
    "encoded": r"=$|=[0-9A-F]{2}|^\w+=|[^\x21-\x7e]",
    "one kind of case": r"^[A-Z0-9_]+$|^[a-z0-9_]+$",
    "word then joiner": r"^[A-Za-z]+[_-][A-Za-z0-9_-]*$",
}
NOT_A_PASSWORD_EACH = {k: re.compile(v) for k, v in NOT_A_PASSWORD_PARTS.items()}
NOT_A_PASSWORD = re.compile("|".join(f"(?:{v})" for v in NOT_A_PASSWORD_PARTS.values()))


def why_not(tok):
    """Names of the exclusions a token matches, for checking misses without printing the token."""
    return [k for k, p in NOT_A_PASSWORD_EACH.items() if p.search(tok)]


def _words():
    """Every Mac has /usr/share/dict/words (web2, 235k words); BIP39's list stands in where it's missing."""
    try:
        return frozenset(w.lower() for w in Path("/usr/share/dict/words").read_text().split() if len(w) >= 3) | WORDS
    except OSError:
        return WORDS


DICT = None
SEGMENT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def _wordy(tok):
    """A name made of words (iPhone15Pro, GPT4o-mini, MacBookAir2) rather than drawn at random: words of three or
    more letters cover at least two fifths of it."""
    global DICT
    if DICT is None:
        DICT = _words()
    covered = sum(len(seg) for seg in SEGMENT.findall(tok) if len(seg) >= 3 and seg.lower() in DICT)
    return covered * 5 >= len(tok) * 2


RUN = re.compile(r"[a-z]+|[A-Z]+|\d+|[^A-Za-z0-9]+")
# Apple's suggested strong password: three groups of six joined by hyphens, one capital and one digit among them.
APPLE = re.compile(r"^(?=.*[A-Z])(?=.*\d)[A-Za-z0-9]{6}-[A-Za-z0-9]{6}-[A-Za-z0-9]{6}$")
PART = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|\d+[A-Za-z]{0,2}|[A-Za-z]{1,4}\d+[a-z]?|")


def _named(tok):
    """Parts joined by - _ . : each of which is a word, capitals, a number with a unit or a letters-then-number
    (Qwen2.5-72B-Instruct, GPT4o-mini, Llama-3.1-8B): a model, part or build name."""
    parts = re.split(r"[-_.:+]", tok)
    return (len(parts) >= 2 and all(PART.fullmatch(p) for p in parts)
            and any(len(p) >= 3 and p.isalpha() for p in parts))  # a word among them, unlike N7x-Qf2r-Lp8k


def _random_looking(tok):
    """Drawn at random rather than written: lower, upper and digit all in it, no run of one kind longer than six
    (a word, a part number's capitals), and the kind changes at least every other character or so. Part numbers,
    math and words with a comma after them, alone on a line in a PDF's text, fail one of these."""
    if APPLE.match(tok):
        return True
    if not (re.search(r"[a-z]", tok) and re.search(r"[A-Z]", tok) and re.search(r"\d", tok)) or _named(tok):
        return False
    runs = RUN.findall(tok)
    # all four kinds in it is rarer by chance than three, so it may change kind less often
    share = 0.3 if re.search(r"[^A-Za-z0-9]", tok) else 0.45
    return max(map(len, runs)) <= 6 and len(runs) - 1 >= share * (len(tok) - 1)


# Inside a sentence ("the db one is ... for now") a password has to look even more drawn at random: 12 or more
# characters, a symbol among them (most IDs and hashes in prose have none), and trailing punctuation set aside.
INLINE = re.compile(r"(?<![\S])(?P<q>[`'\"]?)(?P<tok>[^\s`'\"()\[\]<>]{12,40}?)(?P=q)(?=[.,;:!?)]*(?:\s|$))")


def _inline(m):
    tok = m.group("tok")
    if re.search(r"[^A-Za-z0-9]", tok) and _password_like(tok, False) and not tok.startswith("[redacted"):
        return m.group("q") + "[redacted password]" + m.group("q")
    return m.group(0)


# A label that says what the token is and it isn't a password: an ID, a reference, an order or ticket number.
ID_LABEL = re.compile(r"(?i)\b(?:id|ids|ref|reference|order|invoice|ticket|case|tracking|booking|confirmation|serial|"
                      r"sku|model|part|cid|uuid|hash|commit|build|version|code)\b\W*$|[\[@<]")


# A generator's output can start with [ or ~, hold two slashes or end in ), so markup, path, number and code
# rules catch it by accident. Links, emails, file names and tags still win.
STRONG = re.compile("|".join(f"(?:{NOT_A_PASSWORD_PARTS[k]})" for k in ("link", "email", "file name", "tag or variable", "encoded")))


CODEISH = re.compile(r"\([^()]*\)|\{[^{}]*\}|<[^<>]*>|\[[^\[\]]*\]|::|%[0-9A-Fa-f]{2}|[=$]|\.~|&#?\w+;|\*\*|`|/[^/]*/")


def _generated(tok):
    """Mixed case, digits and three or more kinds of symbol (not the . / - _ paths and names are made of), drawn at
    random: a generator's, whatever else it happens to look like."""
    kinds = set(re.findall(r"[^A-Za-z0-9./_-]", tok))
    # a backslash is LaTeX (\cite{Smith2024}) or Windows, not a password generator
    # matched brackets, ::, %2F escapes, = and $ are code, math and URLs; a generator rarely pairs them up
    return ("\\" not in tok and not CODEISH.search(tok) and len(kinds) >= 3 and re.search(r"[a-z]", tok) and re.search(r"[A-Z]", tok) and re.search(r"\d", tok)
            and not STRONG.search(tok) and _random_looking(tok))


def _password_like(tok, alone):
    """Drawn at random, Apple's format, or (alone on its line) letters, a digit and a symbol that aren't words, the
    way people make their own: not a link, path, name or ID."""
    tok = QUOTED.sub(r"\2", tok)
    if not 10 <= len(tok) <= 40:
        return False
    if NOT_A_PASSWORD.search(tok.rstrip(".,;")) and not APPLE.match(tok) and not (alone and _generated(tok)):
        return False
    # words in it are fine when a symbol people put in passwords is too (Purple7!Horse); without one it's a name
    wordy = _wordy(tok) and not re.search(r"[!@#$%^*?~+]", tok)
    if APPLE.match(tok) or _random_looking(tok):
        return not wordy
    core = tok.rstrip(".,;:")
    # a person's own: a symbol people put in passwords, none of the ones times, money, markup and addresses use
    return bool(alone and re.search(r"[A-Za-z]", core) and re.search(r"\d", core) and re.search(r"[!@#$%^*?~+_]", core)
                and not re.search(r"[:;<>/&|=,\\]|\$\d", core) and not _named(core) and not wordy and len(core) >= 10)


def _standalone(m):
    rest = m.group("rest")
    if " " not in rest and "\t" not in rest and _password_like(rest, True):
        return m.group("keep") + "[redacted password]"
    lab = LABELLED.match(rest)
    if lab and not ID_LABEL.search(m.group("keep") + lab.group("label")) and _password_like(lab.group("tok"), True):
        return m.group("keep") + lab.group("label") + "[redacted password]"
    return m.group(0)


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
    text = STANDALONE.sub(_standalone, text)
    text = INLINE.sub(_inline, text)
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
