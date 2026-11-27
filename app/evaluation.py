"""Offline categorical quality evaluation and reviewed fixtures for generated cards."""

import re
from dataclasses import dataclass

from app.generator import GLOSSARY
from app.schemas import (
    CLOZE_BLANK_RE,
    MAX_LISTENING_CHARS,
    CardEvaluationChecks,
    CardEvaluationOut,
    CheckStatus,
    EvaluationStatus,
    Kind,
)

MAX_FIELD_CHARS = 5000
FALLBACK_TOPIC = "the technical responsibilities in this text"

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
MEANINGFUL_WORD_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]+")
WORD_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*")
CONTENT_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]+")
UNRESOLVED_RE = re.compile(r"\b(?:TODO|TBD)\b|\?\?\?", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9 _/-]{0,60}\]")
SCAFFOLD_HINT_RE = re.compile(
    r"\b(?:use\s+star|star\s+scaffold|truthful\s+example|real\s+experience|"
    r"do\s+not\s+invent|never\s+invent|practice\s+prompt)\b",
    re.IGNORECASE,
)

_NUMBER_PATTERN = r"\d+(?:,\d+)*(?:\.\d+)?"
METRIC_RE = re.compile(
    rf"(?:\$\s?{_NUMBER_PATTERN}(?!\d)(?![,.]\d)|"
    rf"(?<![\d,.$])\b{_NUMBER_PATTERN}\s?(?:%|(?:percent|x|ms|seconds?|minutes?|hours?|days?|"
    r"years?|engineers?|servers?|accounts?|clusters?|nodes?|microservices?|services?|"
    r"tickets?|incidents?)\b))",
    re.IGNORECASE,
)
CLAUSE_NUMBER_RE = re.compile(rf"(?<![\d,.])\b{_NUMBER_PATTERN}(?!\d)(?![,.]\d)")
CLAUSE_SPLIT_RE = re.compile(
    r"(?:\.(?!\d)|[!?;:\n])+"
    r"|,\s+(?:while|whereas|but|although|though|and)\b"
    r"|\b(?:while|whereas|but|although|though)\b"
    r"|\band\s+(?=(?:my|our|their|his|her|he|she|they|i|we)\b)",
    re.IGNORECASE,
)

FIRST_PERSON_CLAIM_RE = re.compile(
    r"\b(?:i|we)(?:\s+have|'ve)?\s+(?:"
    r"led|built|designed|architected|migrated|reduced|improved|increased|cut|saved|"
    r"managed|owned|maintained|deployed|automated|created|implemented|developed|"
    r"resolved|fixed|troubleshot|configured|optimized|scaled|delivered|launched|"
    r"supported|administered|operated|monitored|wrote|authored|spearheaded|drove|"
    r"achieved|eliminated|prevented|handled|worked\s+(?:with|on)"
    r")\b",
    re.IGNORECASE,
)
PRACTICE_CLAIM_CLAUSE_RE = re.compile(
    r"^(?:i|we)(?:\s+have)?\s+worked\s+with\s+"
    r"([a-z0-9_./+-]+(?:\s+[a-z0-9_./+-]+){0,2})\s+to\s+"
    r"\[[a-z][a-z0-9 _/-]{0,60}\]$",
    re.IGNORECASE,
)
DIRECTIONAL_BINDING_RE = re.compile(
    r"\b(from|to|into|by|under|below|over|above|at)\s+"
    r"(?:(?:a|an|the)\s+)?"
    r"(\$?\d+(?:,\d+)*(?:\.\d+)?[a-z%]*|[a-z][a-z0-9_-]*)",
    re.IGNORECASE,
)
SCAFFOLD_TEMPLATE_TOKENS: frozenset[str] = frozenset(
    {
        "practice",
        "worked",
        "work",
        "working",
        "task",
        "truthful",
        "example",
        "explain",
        "contribution",
        "star",
        "describe",
        "situation",
        "action",
        "result",
        "choose",
        "real",
        "experience",
        "invent",
        "outcome",
    }
)

TECHNICAL_CONTRADICTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bsecurity\s+groups?\b(?:\s+(?:are|is|act(?:s)?\s+as|behave(?:s)?\s+as))"
            r"(?:\s+(?:a|an))?\s+stateless\b|\bstateless\s+security\s+groups?\b",
            re.IGNORECASE,
        ),
        "Technical contradiction: AWS security groups are stateful, not stateless.",
    ),
    (
        re.compile(
            r"\b(?:network\s+acls?|nacls?)\b(?:\s+(?:are|is|act(?:s)?\s+as|behave(?:s)?\s+as))"
            r"(?:\s+(?:a|an))?\s+stateful\b|\bstateful\s+(?:network\s+acls?|nacls?)\b",
            re.IGNORECASE,
        ),
        "Technical contradiction: network ACLs (NACLs) are stateless, not stateful.",
    ),
    (
        re.compile(
            r"\btcp\b(?:\s+(?:is|remains|acts?\s+as))(?:\s+(?:a|an))?\s+"
            r"(?:connectionless|unreliable)\b|\b(?:connectionless|unreliable)\s+tcp\b",
            re.IGNORECASE,
        ),
        (
            "Technical contradiction: TCP is connection-oriented and reliable, "
            "not connectionless or unreliable."
        ),
    ),
    (
        re.compile(
            r"\budp\b(?:\s+(?:is|remains|acts?\s+as))(?:\s+(?:a|an))?\s+connection[- ]oriented\b|"
            r"\bconnection[- ]oriented\s+udp\b|"
            r"\budp\b(?:\s+(?:uses?|performs?|requires?|establishes?))(?:\s+(?:a|the))?\s+"
            r"(?:3|three)[- ]way\s+handshake\b|"
            r"\b(?:3|three)[- ]way\s+handshake\s+(?:in|for|of)\s+udp\b",
            re.IGNORECASE,
        ),
        "Technical contradiction: UDP is connectionless and does not use a three-way handshake.",
    ),
    (
        re.compile(
            r"\biam\s+roles?\b(?:\s+(?:provide|provides|use|uses|issue|issues|grant|grants|"
            r"have|has|store|stores|give|gives))(?:\s+(?:only|the))?\s+"
            r"(?:permanent|static|long[- ]term)\s+(?:access\s+)?(?:credentials?|keys?)\b|"
            r"\b(?:permanent|static|long[- ]term)\s+iam\s+role\s+(?:credentials?|keys?)\b",
            re.IGNORECASE,
        ),
        (
            "Technical contradiction: IAM roles provide temporary credentials, "
            "not permanent or static keys."
        ),
    ),
    (
        re.compile(
            r"\b(?:postgresql|postgres|sql)\b(?:\s+(?:is|are))(?:\s+(?:a|an))?\s+"
            r"(?:nosql|non[- ]relational|document)\b|"
            r"\b(?:nosql|non[- ]relational)\s+(?:postgresql|postgres)\b",
            re.IGNORECASE,
        ),
        "Technical contradiction: PostgreSQL and SQL are relational, not NoSQL.",
    ),
    (
        re.compile(
            r"\bdocker\b(?:\s+is)(?:\s+(?:a|an))?\s+"
            r"(?:programming\s+language|relational\s+database|sql\s+database|hypervisor)\b",
            re.IGNORECASE,
        ),
        (
            "Technical contradiction: Docker is a container platform, "
            "not a programming language, relational database, or hypervisor."
        ),
    ),
    (
        re.compile(
            r"\bpython\b(?:\s+is)(?:\s+(?:a|an))?\s+"
            r"(?:relational\s+database|sql\s+database|operating\s+system)\b",
            re.IGNORECASE,
        ),
        (
            "Technical contradiction: Python is a programming language, "
            "not a relational database or operating system."
        ),
    ),
    (
        re.compile(
            r"\blinux\b(?:\s+is)(?:\s+(?:a|an))?\s+"
            r"(?:relational\s+database|sql\s+database|programming\s+language)\b",
            re.IGNORECASE,
        ),
        (
            "Technical contradiction: Linux is an operating system, "
            "not a relational database or programming language."
        ),
    ),
    (
        re.compile(
            r"\bterraform\b(?:\s+is)(?:\s+(?:a|an))?\s+"
            r"(?:relational\s+database|sql\s+database|container\s+runtime)\b",
            re.IGNORECASE,
        ),
        (
            "Technical contradiction: Terraform is an infrastructure-as-code tool, "
            "not a relational database or container runtime."
        ),
    ),
)

STOPWORDS: frozenset[str] = frozenset(
    {
        "about",
        "after",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "done",
        "during",
        "each",
        "explain",
        "few",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "him",
        "his",
        "how",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "may",
        "me",
        "might",
        "more",
        "most",
        "must",
        "my",
        "no",
        "not",
        "of",
        "on",
        "one",
        "only",
        "onto",
        "or",
        "other",
        "our",
        "over",
        "own",
        "same",
        "shall",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "two",
        "under",
        "up",
        "us",
        "use",
        "used",
        "using",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "whereas",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "within",
        "without",
        "would",
        "you",
        "your",
    }
)


def _add_unique(items: list[str], message: str) -> None:
    if message not in items:
        items.append(message)


def _norm_space(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _strip_urls(text: str) -> str:
    return URL_RE.sub(" ", text)


def _words(text: str) -> list[str]:
    return WORD_RE.findall(_strip_urls(text))


def _meaningful_words(text: str) -> list[str]:
    return MEANINGFUL_WORD_RE.findall(_strip_urls(text))


def _content_tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in CONTENT_TOKEN_RE.findall(_strip_urls(text))
        if len(tok) >= 2 and tok.lower() not in STOPWORDS
    }


def _ordered_content_tokens(text: str) -> list[str]:
    return [
        tok.lower()
        for tok in CONTENT_TOKEN_RE.findall(_strip_urls(text))
        if len(tok) >= 2 and tok.lower() not in STOPWORDS
    ]


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(item in it for item in needle)


def _directional_bindings(text: str) -> set[tuple[str, str]]:
    return {
        (match.group(1).lower(), match.group(2).lower())
        for match in DIRECTIONAL_BINDING_RE.finditer(_norm_space(text))
    }


def _normalize_metric(raw: str) -> str:
    collapsed = " ".join(raw.strip().lower().split())
    collapsed = re.sub(r"^\$\s+", "$", collapsed)
    collapsed = re.sub(r"\s+%$", "%", collapsed)
    collapsed = re.sub(r"^(\d+(?:,\d+)*(?:\.\d+)?)\s*(ms|x)$", r"\1\2", collapsed)
    return collapsed


def _extract_metrics(text: str) -> set[str]:
    return {_normalize_metric(match.group(0)) for match in METRIC_RE.finditer(text)}


def _clauses(text: str) -> list[str]:
    stripped = _strip_urls(text)
    return [part.strip() for part in CLAUSE_SPLIT_RE.split(stripped) if part.strip()]


def _is_practice_scaffold_back(back_text: str, kind: Kind, source_tokens: set[str]) -> bool:
    if kind not in ("behavioral", "interview_phrase"):
        return False
    if not SCAFFOLD_HINT_RE.search(back_text):
        return False
    non_scaffold_tokens = (
        _content_tokens(PLACEHOLDER_RE.sub(" ", back_text)) - SCAFFOLD_TEMPLATE_TOKENS
    )
    return non_scaffold_tokens.issubset(source_tokens)


def _is_exempt_practice_back(back_text: str, kind: Kind, source_tokens: set[str]) -> bool:
    if not _is_practice_scaffold_back(back_text, kind, source_tokens):
        return False
    if not PLACEHOLDER_RE.search(back_text):
        return False
    claim_clauses = [
        clause for clause in _clauses(back_text) if FIRST_PERSON_CLAIM_RE.search(clause)
    ]
    if not claim_clauses:
        return False
    for clause in claim_clauses:
        match = PRACTICE_CLAIM_CLAUSE_RE.fullmatch(_norm_space(clause))
        if match is None:
            return False
        topic = match.group(1)
        if "to" in topic.lower().split():
            return False
        topic_tokens = _content_tokens(topic)
        if not topic_tokens or not topic_tokens.issubset(source_tokens):
            return False
    return True


def _claim_clause_supported(card_clause: str, source_clauses: list[str]) -> bool:
    claim_phrases = [_norm_space(match) for match in FIRST_PERSON_CLAIM_RE.findall(card_clause)]
    if not claim_phrases:
        return True
    card_tokens = _content_tokens(card_clause)
    ordered_card_tokens = _ordered_content_tokens(card_clause)
    card_numbers = CLAUSE_NUMBER_RE.findall(card_clause)
    card_bindings = _directional_bindings(card_clause)

    for source_clause in source_clauses:
        norm_source = _norm_space(source_clause)
        if not all(re.search(rf"\b{re.escape(phrase)}\b", norm_source) for phrase in claim_phrases):
            continue
        if not card_tokens.issubset(_content_tokens(source_clause)):
            continue
        if not _is_subsequence(ordered_card_tokens, _ordered_content_tokens(source_clause)):
            continue
        if not _is_subsequence(card_numbers, CLAUSE_NUMBER_RE.findall(source_clause)):
            continue
        if not card_bindings.issubset(_directional_bindings(source_clause)):
            continue
        return True
    return False


def _allowed_answer_tokens(source_tokens: set[str]) -> tuple[set[str], set[str]]:
    glossary_tokens: set[str] = set()
    for term, definition in GLOSSARY.items():
        if term in source_tokens:
            glossary_tokens.update(_content_tokens(definition))
    return source_tokens | glossary_tokens, glossary_tokens


def evaluate_generated_card(
    *,
    front: str,
    back: str,
    kind: Kind,
    source_text: str,
    accepted_answers: list[str] | tuple[str, ...] = (),
    explanation: str | None = None,
) -> CardEvaluationOut:
    """Run deterministic offline categorical checks on a generated card draft."""
    raw_explanation = explanation or ""
    raw_answers = list(accepted_answers)
    raw_fields = (front, back, raw_explanation, *raw_answers)

    cleaned_front = front.strip()
    cleaned_back = back.strip()
    cleaned_explanation = raw_explanation.strip()
    cleaned_answers = [ans.strip() for ans in raw_answers if ans.strip()]
    all_cleaned_fields = (cleaned_front, cleaned_back, cleaned_explanation, *cleaned_answers)

    english_usefulness: CheckStatus = "pass"
    technical_accuracy: CheckStatus = "pass"
    ambiguity: CheckStatus = "pass"
    source_grounding: CheckStatus = "pass"
    uncertainty: list[str] = []
    rejection_reasons: list[str] = []

    min_back_words = 1 if kind == "cloze" else 2
    front_words = _words(cleaned_front)
    back_words = _words(cleaned_back)

    source_tokens = _content_tokens(source_text)
    has_placeholder = any(bool(PLACEHOLDER_RE.search(part)) for part in all_cleaned_fields if part)
    is_practice_scaffold = _is_practice_scaffold_back(cleaned_back, kind, source_tokens)

    # 1. english_usefulness
    if any("\x00" in part for part in raw_fields):
        english_usefulness = "fail"
        _add_unique(rejection_reasons, "Card fields must not contain NUL bytes.")

    if any(len(part) > MAX_FIELD_CHARS for part in all_cleaned_fields):
        english_usefulness = "fail"
        _add_unique(
            rejection_reasons,
            f"Card fields must be at most {MAX_FIELD_CHARS} characters.",
        )

    if kind == "listening" and len(cleaned_back) > MAX_LISTENING_CHARS:
        english_usefulness = "fail"
        _add_unique(
            rejection_reasons,
            f"Listening card back must be at most {MAX_LISTENING_CHARS} characters.",
        )

    for label, text_value, min_words in (
        ("front", cleaned_front, 2),
        ("back", cleaned_back, min_back_words),
    ):
        has_url = bool(URL_RE.search(text_value))
        meaningful = _meaningful_words(text_value)
        words = _words(text_value)
        if not meaningful:
            english_usefulness = "fail"
            if has_url:
                _add_unique(
                    rejection_reasons,
                    f"Card {label} is a bare URL without meaningful English words.",
                )
            else:
                _add_unique(
                    rejection_reasons,
                    f"Card {label} must contain meaningful alphabetic English words.",
                )
        elif len(words) < min_words:
            english_usefulness = "fail"
            _add_unique(
                rejection_reasons,
                f"Card {label} must contain at least {min_words} English word(s).",
            )

    if cleaned_explanation:
        exp_meaningful = _meaningful_words(cleaned_explanation)
        exp_words = _words(cleaned_explanation)
        if not exp_meaningful or len(exp_words) < 2:
            english_usefulness = "fail"
            _add_unique(
                rejection_reasons,
                "Card explanation must contain at least 2 meaningful English words.",
            )

    for ans in cleaned_answers:
        ans_meaningful = _meaningful_words(ans)
        ans_words = _words(ans)
        if not ans_meaningful or len(ans_words) < min_back_words:
            english_usefulness = "fail"
            _add_unique(
                rejection_reasons,
                f"Card accepted_answers entries must contain at least {min_back_words} "
                "meaningful English word(s).",
            )

    # 2. technical_accuracy
    for part in all_cleaned_fields:
        if not part:
            continue
        for clause in _clauses(part):
            for pattern, message in TECHNICAL_CONTRADICTIONS:
                if pattern.search(clause):
                    technical_accuracy = "fail"
                    _add_unique(rejection_reasons, message)

    source_metrics = _extract_metrics(source_text)
    for part in all_cleaned_fields:
        if not part:
            continue
        card_metrics = _extract_metrics(part)
        if card_metrics - source_metrics:
            technical_accuracy = "fail"
            _add_unique(
                rejection_reasons,
                "Card contains ungrounded metrics not present in source_text.",
            )

    source_clauses = _clauses(source_text)
    named_fields: tuple[tuple[str, str], ...] = (
        ("front", cleaned_front),
        ("back", cleaned_back),
        ("explanation", cleaned_explanation),
        *(("accepted_answer", ans) for ans in cleaned_answers),
    )
    for field_name, part in named_fields:
        if not part:
            continue
        if field_name == "back" and _is_exempt_practice_back(part, kind, source_tokens):
            continue
        if not FIRST_PERSON_CLAIM_RE.search(part):
            continue
        claim_clauses = [
            clause for clause in _clauses(part) if FIRST_PERSON_CLAIM_RE.search(clause)
        ]
        if not claim_clauses or any(
            not _claim_clause_supported(clause, source_clauses) for clause in claim_clauses
        ):
            technical_accuracy = "fail"
            _add_unique(
                rejection_reasons,
                "Card makes a first-person achievement claim not supported by source_text.",
            )

    # 3. ambiguity
    norm_front = _norm_space(cleaned_front)
    norm_back = _norm_space(cleaned_back)
    if norm_front == norm_back:
        ambiguity = "fail"
        _add_unique(rejection_reasons, "Card front and back must not be identical.")

    if cleaned_explanation and _norm_space(cleaned_explanation) == norm_front:
        ambiguity = "fail"
        _add_unique(rejection_reasons, "Card explanation must not repeat the front verbatim.")

    if any(_norm_space(ans) == norm_front for ans in cleaned_answers):
        ambiguity = "fail"
        _add_unique(
            rejection_reasons,
            "Card accepted_answers must not repeat the front verbatim.",
        )

    if len(front_words) < 2:
        ambiguity = "fail"
        _add_unique(rejection_reasons, "Card front is too short to form an unambiguous prompt.")

    if len(back_words) < min_back_words:
        ambiguity = "fail"
        _add_unique(rejection_reasons, "Card back is too short to form an unambiguous answer.")

    if cleaned_explanation and len(_words(cleaned_explanation)) < 2:
        ambiguity = "fail"
        _add_unique(rejection_reasons, "Card explanation is too short to clarify the answer.")

    if any(len(_words(ans)) < min_back_words for ans in cleaned_answers):
        ambiguity = "fail"
        _add_unique(
            rejection_reasons,
            "Card accepted_answers contain an entry that is too short to be unambiguous.",
        )

    if any(UNRESOLVED_RE.search(part) for part in all_cleaned_fields if part):
        ambiguity = "fail"
        _add_unique(rejection_reasons, "Card contains unresolved markers (TODO, TBD, or ???).")

    if kind == "cloze" and CLOZE_BLANK_RE.findall(cleaned_front) != ["____"]:
        ambiguity = "fail"
        _add_unique(rejection_reasons, "Cloze card front must contain exactly one '____' blank.")

    if has_placeholder:
        _add_unique(
            uncertainty,
            "Draft contains a bracketed placeholder; replace it with specific "
            "truthful details before studying.",
        )

    if kind in ("cloze", "es_en") and not cleaned_answers:
        _add_unique(
            uncertainty,
            "No accepted_answers are listed; consider adding valid synonyms or phrasing variants.",
        )

    if ambiguity == "pass" and (
        has_placeholder or (kind in ("cloze", "es_en") and not cleaned_answers)
    ):
        ambiguity = "warn"

    # 4. source_grounding
    if any(FALLBACK_TOPIC in _norm_space(part) for part in all_cleaned_fields if part):
        source_grounding = "fail"
        _add_unique(
            rejection_reasons,
            "Card uses generic fallback topic text instead of terms grounded in source_text.",
        )

    allowed_tokens, glossary_tokens = _allowed_answer_tokens(source_tokens)
    front_tokens = _content_tokens(cleaned_front)
    back_tokens = _content_tokens(cleaned_back)

    if not (source_tokens & (front_tokens | back_tokens)):
        source_grounding = "fail"
        _add_unique(rejection_reasons, "Card is not grounded in any content term from source_text.")

    allow_scaffold_back = (
        is_practice_scaffold
        and kind in ("behavioral", "interview_phrase")
        and bool(front_tokens & source_tokens)
    )
    if not (back_tokens & allowed_tokens) and not allow_scaffold_back:
        source_grounding = "fail"
        _add_unique(rejection_reasons, "Card back is not grounded in source_text.")

    if any(not (_content_tokens(ans) & allowed_tokens) for ans in cleaned_answers):
        source_grounding = "fail"
        _add_unique(
            rejection_reasons,
            "Card accepted_answers contain an entry not grounded in source_text.",
        )

    if cleaned_explanation and not (_content_tokens(cleaned_explanation) & allowed_tokens):
        source_grounding = "fail"
        _add_unique(rejection_reasons, "Card explanation is not grounded in source_text.")

    checks = CardEvaluationChecks(
        english_usefulness=english_usefulness,
        technical_accuracy=technical_accuracy,
        ambiguity=ambiguity,
        source_grounding=source_grounding,
    )
    ready_for_review = all(
        status != "fail"
        for status in (english_usefulness, technical_accuracy, ambiguity, source_grounding)
    )
    status: EvaluationStatus = "draft" if ready_for_review else "rejected"

    if ready_for_review:
        if is_practice_scaffold:
            _add_unique(
                uncertainty,
                "Practice scaffold requires a truthful personal example during study; "
                "offline checks cannot verify personal history.",
            )
        if back_tokens and not (back_tokens & source_tokens) and (back_tokens & glossary_tokens):
            _add_unique(
                uncertainty,
                "Answer wording relies on the built-in offline glossary definition "
                "rather than direct phrasing in source_text.",
            )
        _add_unique(
            uncertainty,
            "Offline checks verify lexical grounding and known contradiction rules only; "
            "review technical nuance before approving.",
        )

    return CardEvaluationOut(
        status=status,
        ready_for_review=ready_for_review,
        checks=checks,
        uncertainty=uncertainty,
        rejection_reasons=rejection_reasons,
    )


@dataclass(frozen=True)
class EvaluationFixtureCase:
    name: str
    front: str
    back: str
    kind: Kind
    expected_status: EvaluationStatus
    expected_checks: dict[str, CheckStatus]
    accepted_answers: tuple[str, ...] = ()
    explanation: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class EvaluationFixture:
    id: str
    category: str
    source_label: str
    source_text: str
    cases: tuple[EvaluationFixtureCase, ...]


EVALUATION_FIXTURES: tuple[EvaluationFixture, ...] = (
    EvaluationFixture(
        id="vacancy-cloud-support",
        category="vacancy",
        source_label="vacancy:cloud-support-engineer",
        source_text=(
            "Cloud Support Engineer vacancy: troubleshoot AWS, Linux, Python, and PostgreSQL "
            "incidents, monitor API latency under 200ms, and write clear customer updates."
        ),
        cases=(
            EvaluationFixtureCase(
                name="clean-vocabulary-draft",
                front="Explain 'postgresql' in technical English.",
                back="A relational database supporting SQL and transactions.",
                kind="vocabulary",
                explanation=(
                    "PostgreSQL supports relational data and ACID transactions "
                    "for cloud support workloads."
                ),
                expected_status="draft",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "pass",
                    "ambiguity": "pass",
                    "source_grounding": "pass",
                },
                notes="Glossary-backed vocabulary draft grounded in vacancy source_text.",
            ),
            EvaluationFixtureCase(
                name="interview-scaffold-placeholder-warn",
                front="How would you discuss your experience with aws?",
                back=(
                    "Practice: I have worked with aws to [task]. "
                    "Use a truthful example and explain your contribution."
                ),
                kind="interview_phrase",
                expected_status="draft",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "pass",
                    "ambiguity": "warn",
                    "source_grounding": "pass",
                },
                notes=(
                    "Editable practice scaffold with [task] placeholder triggers ambiguity warning."
                ),
            ),
            EvaluationFixtureCase(
                name="fabricated-achievement-metric-rejected",
                front="How did you handle Linux and API incidents?",
                back="I reduced API latency by 70% across 200 servers and saved $50,000.",
                kind="behavioral",
                expected_status="rejected",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "fail",
                    "ambiguity": "pass",
                    "source_grounding": "pass",
                },
                notes="Rejects invented first-person claim and ungrounded metrics.",
            ),
            EvaluationFixtureCase(
                name="fallback-generic-ungrounded-rejected",
                front=(
                    "How would you discuss your experience with "
                    "the technical responsibilities in this text?"
                ),
                back=(
                    "Practice: I have worked with the technical responsibilities in this text "
                    "to [task]. Use a truthful example."
                ),
                kind="interview_phrase",
                expected_status="rejected",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "fail",
                    "ambiguity": "warn",
                    "source_grounding": "fail",
                },
                notes="Rejects generic MockGenerator fallback topic cards.",
            ),
        ),
    ),
    EvaluationFixture(
        id="aws-docs-vpc-iam",
        category="aws_docs",
        source_label="aws-docs:vpc-iam",
        source_text=(
            "AWS VPC security groups act as stateful virtual firewalls for EC2 instances, "
            "while network ACLs are stateless at the subnet boundary. Route tables match "
            "destination IP CIDR blocks. IAM roles provide temporary security credentials "
            "instead of long-term static keys."
        ),
        cases=(
            EvaluationFixtureCase(
                name="cloze-ip-warn-no-accepted-answers",
                front="VPC route tables match destination ____ CIDR blocks.",
                back="IP",
                kind="cloze",
                expected_status="draft",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "pass",
                    "ambiguity": "warn",
                    "source_grounding": "pass",
                },
                notes=(
                    "Preserves 2-char technical term 'IP' and warns when cloze "
                    "has no accepted_answers."
                ),
            ),
            EvaluationFixtureCase(
                name="cloze-iam-with-accepted-answers-pass",
                front="IAM roles issue ____ security credentials for AWS workloads.",
                back="temporary",
                kind="cloze",
                accepted_answers=("short-lived temporary credentials",),
                explanation=(
                    "IAM roles avoid long-term static keys by issuing temporary credentials."
                ),
                expected_status="draft",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "pass",
                    "ambiguity": "pass",
                    "source_grounding": "pass",
                },
                notes="Cloze card with grounded accepted_answers and explanation passes cleanly.",
            ),
            EvaluationFixtureCase(
                name="contradiction-stateless-sg-rejected",
                front="How do AWS VPC security groups filter traffic?",
                back="AWS security groups are stateless firewalls at the instance level.",
                kind="vocabulary",
                expected_status="rejected",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "fail",
                    "ambiguity": "pass",
                    "source_grounding": "pass",
                },
                notes="Rejects technical contradiction claiming security groups are stateless.",
            ),
            EvaluationFixtureCase(
                name="bare-url-unusable-rejected",
                front="https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html",
                back="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html",
                kind="vocabulary",
                expected_status="rejected",
                expected_checks={
                    "english_usefulness": "fail",
                    "technical_accuracy": "pass",
                    "ambiguity": "fail",
                    "source_grounding": "fail",
                },
                notes="Rejects bare URLs without usable English study text.",
            ),
        ),
    ),
    EvaluationFixture(
        id="interview-networking-star",
        category="interview",
        source_label="interview:networking-star",
        source_text=(
            "Networking interview prep: TCP is connection-oriented and uses a three-way "
            "handshake for reliable ordered delivery, whereas UDP is connectionless. "
            "In our rehearsal notes, I led the PostgreSQL migration and cut query latency "
            "by 1,170ms. My colleague led the Docker migration."
        ),
        cases=(
            EvaluationFixtureCase(
                name="clean-tcp-udp-contrast-draft",
                front="How do TCP and UDP differ in networking interviews?",
                back=(
                    "TCP is connection-oriented with a three-way handshake for reliable "
                    "delivery, whereas UDP is connectionless."
                ),
                kind="interview_phrase",
                expected_status="draft",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "pass",
                    "ambiguity": "pass",
                    "source_grounding": "pass",
                },
                notes="Valid TCP vs UDP contrast does not false-positive on contradiction rules.",
            ),
            EvaluationFixtureCase(
                name="grounded-single-sentence-claim-draft",
                front="What database migration did you lead in your rehearsal notes?",
                back="I led the PostgreSQL migration and cut query latency by 1,170ms.",
                kind="behavioral",
                expected_status="draft",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "pass",
                    "ambiguity": "pass",
                    "source_grounding": "pass",
                },
                notes="Single-sentence grounded claim with exact comma-separated metric passes.",
            ),
            EvaluationFixtureCase(
                name="contradiction-udp-handshake-rejected",
                front="How does UDP establish a session?",
                back=(
                    "UDP is connection-oriented and uses a three-way handshake "
                    "before sending packets."
                ),
                kind="interview_phrase",
                expected_status="rejected",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "fail",
                    "ambiguity": "pass",
                    "source_grounding": "pass",
                },
                notes="Rejects UDP connection-oriented / three-way handshake contradiction.",
            ),
            EvaluationFixtureCase(
                name="cross-sentence-claim-suffix-metric-todo-rejected",
                front="Which container migration did you lead?",
                back="I led the Docker migration and cut latency by 170ms. TODO add details.",
                kind="behavioral",
                expected_status="rejected",
                expected_checks={
                    "english_usefulness": "pass",
                    "technical_accuracy": "fail",
                    "ambiguity": "fail",
                    "source_grounding": "pass",
                },
                notes=(
                    "Rejects cross-sentence claim, suffix metric 170ms vs 1,170ms, and TODO marker."
                ),
            ),
        ),
    ),
)
