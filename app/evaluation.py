"""Offline categorical evaluation and reviewed fixtures for generated cards."""

import re
from dataclasses import dataclass
from typing import Literal

from app.generator import GLOSSARY
from app.schemas import (
    CLOZE_BLANK_RE,
    CardEvaluationChecks,
    CardEvaluationOut,
    CheckStatus,
    EvaluationStatus,
    Kind,
)

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
ALPHA_WORD_RE = re.compile(r"[A-Za-z]{2,}")
UNRESOLVED_RE = re.compile(r"(?:\b(?:TODO|TBD)\b|\?\?\?)", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\[[A-Za-z0-9 _-]{2,30}\]")
SCAFFOLD_HINT_RE = re.compile(
    r"\b(?:use\s+a\s+truthful\s+example|do\s+not\s+invent|use\s+star\s*:|choose\s+a\s+real\s+experience)\b",
    re.IGNORECASE,
)
FIRST_PERSON_PRONOUN_RE = re.compile(r"\b(?:i|my|we|our)\b", re.IGNORECASE)
FIRST_PERSON_CLAIM_RE = re.compile(
    r"\b(?:i|we)\s+(?:have\s+)?(?:reduced|cut|improved|increased|saved|led|managed|built|"
    r"migrated|resolved|fixed|deployed|architected|designed|scaled|achieved|delivered|"
    r"maintained|automated|handled|owned|implemented|worked\s+with)\b"
    r"|\bin\s+my\s+(?:last|previous)\s+(?:role|job|company|position)\b",
    re.IGNORECASE,
)
METRIC_RE = re.compile(
    r"(?:\$\s?\d[\d,.]*|\b\d+(?:\.\d+)?\s?(?:%|percent|x|ms|seconds?|minutes?|hours?|days?|"
    r"years?|engineers?|servers?|accounts?|clusters?|nodes?|microservices?|services?|"
    r"tickets?|incidents?)\b)",
    re.IGNORECASE,
)
FALLBACK_TOPIC = "the technical responsibilities in this text"

TECHNICAL_CONTRADICTIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), message)
    for pattern, message in (
        (
            r"\bsecurity\s+groups?\s+(?:are|is|remain|act\s+as|operate\s+as)\s+(?:a\s+)?stateless\b"
            r"|(?<!not\s)(?<!unlike\s)\bstateless\s+security\s+groups?\b",
            "Technical inaccuracy: AWS VPC security groups are stateful, not stateless.",
        ),
        (
            r"\b(?:nacl|nacls|network\s+acls?)\s+(?:are|is|remain|act\s+as|operate\s+as)\s+"
            r"(?:a\s+)?stateful\b|(?<!not\s)(?<!unlike\s)\bstateful\s+(?:nacl|nacls|network\s+acls?)\b",
            "Technical inaccuracy: AWS VPC network ACLs are stateless, not stateful.",
        ),
        (
            r"\btcp\s+(?:is|remains|operates\s+as)\s+(?:a\s+)?(?:connectionless|unreliable)\b"
            r"|(?<!not\s)(?<!unlike\s)\bconnectionless\s+tcp\b",
            "Technical inaccuracy: TCP is connection-oriented, not connectionless.",
        ),
        (
            r"\budp\s+(?:is|remains|operates\s+as)\s+(?:a\s+)?connection[- ]oriented\b"
            r"|\budp\s+uses?\s+(?:a\s+)?three[- ]way\s+handshake\b",
            "Technical inaccuracy: UDP is connectionless and does not use a three-way handshake.",
        ),
        (
            r"\biam\s+roles?\s+(?:use|provide|issue|grant|store)\s+"
            r"(?:permanent|static|long[- ]term)\s+(?:credentials?|keys?)\b",
            "Technical inaccuracy: IAM roles provide temporary credentials, not permanent keys.",
        ),
        (
            r"\b(?:postgresql|postgres|sql)\s+(?:is|are)\s+"
            r"(?:a\s+)?(?:nosql|non[- ]relational|document)\b",
            "Technical inaccuracy: PostgreSQL and SQL are relational, not NoSQL.",
        ),
        (
            r"\bdocker\s+(?:is|are)\s+(?:a\s+)?(?:programming\s+language|relational\s+database|hypervisor)\b",
            "Technical inaccuracy: Docker packages applications in containers.",
        ),
        (
            r"\bpython\s+(?:is|are)\s+(?:an?\s+)?(?:relational\s+database|operating\s+system)\b",
            "Technical inaccuracy: Python is a programming language.",
        ),
        (
            r"\blinux\s+(?:is|are)\s+(?:an?\s+)?(?:relational\s+database|programming\s+language)\b",
            "Technical inaccuracy: Linux is an operating system.",
        ),
        (
            r"\bterraform\s+(?:is|are)\s+(?:an?\s+)?(?:relational\s+database|container\s+runtime)\b",
            "Technical inaccuracy: Terraform is an infrastructure-as-code tool.",
        ),
    )
)

STOPWORDS = frozenset(
    (
        "about action after all also and answer any are been before but can card choose "
        "contribution could describe discuss does english example experience explain for from "
        "had has have how into invent involving its just like make may meaning more most must "
        "need new not one only other our out outcome over own per phrase practice problem "
        "question real result role sentence set should situation solved some star such system "
        "task team technical tell text than that the their them then they this time translate "
        "truthful two use used using very was way what when where which who why will with work "
        "worked would you your"
    ).split()
)


def _strip_urls(text: str) -> str:
    return URL_RE.sub(" ", text)


def _words(text: str) -> list[str]:
    return WORD_RE.findall(_strip_urls(text))


def _stem(token: str) -> str:
    if len(token) >= 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) >= 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _content_tokens(text: str) -> set[str]:
    return {
        stem
        for tok in _words(text)
        if len(tok) >= 3 and (stem := _stem(tok.lower())) not in STOPWORDS
    }


def _norm_space(text: str) -> str:
    return " ".join(text.strip().lower().split())


def evaluate_generated_card(
    *,
    front: str,
    back: str,
    kind: Kind,
    source_text: str,
    accepted_answers: list[str] | tuple[str, ...] = (),
    explanation: str | None = None,
) -> CardEvaluationOut:
    reasons: list[str] = []
    uncertainty: list[str] = []

    front_words, back_words = _words(front), _words(back)
    english_status: CheckStatus = "pass"
    if any("\x00" in part for part in (front, back, explanation or "", *accepted_answers)):
        english_status = "fail"
        reasons.append("Card fields must not contain NUL bytes.")
    if any(len(part.strip()) > 5000 for part in (front, back, explanation or "")):
        english_status = "fail"
        reasons.append("Card fields must be at most 5,000 characters.")
    for side, raw, words in (("front", front, front_words), ("back", back, back_words)):
        alpha = ALPHA_WORD_RE.findall(_strip_urls(raw))
        if URL_RE.search(raw) and not alpha:
            english_status = "fail"
            reasons.append(f"{side} is a bare URL without meaningful English text.")
        elif not alpha:
            english_status = "fail"
            reasons.append(f"{side} contains no meaningful English words.")
        elif len(words) < 2:
            english_status = "fail"
            reasons.append(f"{side} is a single-token fragment; use a clear English phrase.")

    tech_status: CheckStatus = "pass"
    combined_tech = "\n".join(part for part in (front, back, explanation or "") if part)
    for pattern, message in TECHNICAL_CONTRADICTIONS:
        if pattern.search(combined_tech):
            tech_status = "fail"
            reasons.append(message)

    source_norm = _norm_space(source_text)
    ungrounded_metrics = [m for m in METRIC_RE.findall(back) if _norm_space(m) not in source_norm]
    has_placeholder = bool(PLACEHOLDER_RE.search(front) or PLACEHOLDER_RE.search(back))
    is_practice = (
        has_placeholder
        or bool(SCAFFOLD_HINT_RE.search(back))
        or back.strip().lower().startswith("practice:")
    )
    if FIRST_PERSON_CLAIM_RE.search(back):
        if ungrounded_metrics:
            tech_status = "fail"
            reasons.append(
                "Back contains fabricated first-person metrics not grounded in source_text."
            )
        elif not is_practice and not FIRST_PERSON_PRONOUN_RE.search(source_text):
            tech_status = "fail"
            reasons.append(
                "Back makes a first-person achievement claim not supported by source_text."
            )

    ambiguity_status: CheckStatus = "pass"
    if _norm_space(front) == _norm_space(back):
        ambiguity_status = "fail"
        reasons.append("Front and back are identical.")
    if len(front_words) < 2 or len(back_words) < 2:
        ambiguity_status = "fail"
        reasons.append("Front and back must each contain at least two words to avoid ambiguity.")
    if UNRESOLVED_RE.search(front) or UNRESOLVED_RE.search(back):
        ambiguity_status = "fail"
        reasons.append("Card contains unresolved placeholder markers (TODO, TBD, or ???).")
    if kind == "cloze" and CLOZE_BLANK_RE.findall(front) != ["____"]:
        ambiguity_status = "fail"
        reasons.append("Cloze card front must contain exactly one '____' blank.")

    cleaned_answers = [a.strip() for a in accepted_answers if a.strip()]
    if ambiguity_status == "pass" and (
        has_placeholder or (kind in ("cloze", "es_en") and not cleaned_answers)
    ):
        ambiguity_status = "warn"

    grounding_status: CheckStatus = "pass"
    source_tokens = _content_tokens(source_text)
    source_lower_words = {w.lower() for w in _words(source_text)}
    allowed_answer_tokens = set(source_tokens)
    for term, definition in GLOSSARY.items():
        if term in source_lower_words or _stem(term) in source_tokens:
            allowed_answer_tokens |= _content_tokens(definition)
    front_tokens, back_tokens = _content_tokens(front), _content_tokens(back)
    if FALLBACK_TOPIC in front.lower() or FALLBACK_TOPIC in back.lower():
        grounding_status = "fail"
        reasons.append("Card uses the generic fallback placeholder instead of source content.")
    elif not (source_tokens & (front_tokens | back_tokens)):
        grounding_status = "fail"
        reasons.append("Card shares no meaningful technical/content tokens with source_text.")
    elif not (back_tokens & allowed_answer_tokens) and not (
        is_practice
        and kind in ("behavioral", "interview_phrase")
        and (front_tokens & source_tokens)
    ):
        grounding_status = "fail"
        reasons.append("Answer (back) is not grounded in source_text.")

    if has_placeholder:
        uncertainty.append(
            "Contains editable placeholders (e.g. [task]); replace with a truthful example."
        )
    if kind in ("behavioral", "interview_phrase") or SCAFFOLD_HINT_RE.search(back):
        uncertainty.append(
            "Interview/behavioral prompt requires human review to avoid invented outcomes."
        )
    if kind in ("cloze", "es_en") and not cleaned_answers:
        uncertainty.append(
            "No accepted_answers provided for cloze/es_en card; consider adding alternatives."
        )
    uncertainty.append(
        "Offline lexical/rule checks cannot verify technical nuance without human review."
    )

    checks = CardEvaluationChecks(
        english_usefulness=english_status,
        technical_accuracy=tech_status,
        ambiguity=ambiguity_status,
        source_grounding=grounding_status,
    )
    ready = "fail" not in (english_status, tech_status, ambiguity_status, grounding_status)
    return CardEvaluationOut(
        status="draft" if ready else "rejected",
        ready_for_review=ready,
        checks=checks,
        uncertainty=uncertainty,
        rejection_reasons=reasons,
    )


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    front: str
    back: str
    kind: Kind
    expected_status: EvaluationStatus
    expected_failed_checks: tuple[str, ...] = ()
    expected_warn_checks: tuple[str, ...] = ()
    accepted_answers: tuple[str, ...] = ()
    explanation: str | None = None


@dataclass(frozen=True)
class EvaluationFixture:
    id: str
    category: Literal["vacancy", "aws_docs", "interview"]
    source_label: str
    source_text: str
    cases: tuple[EvaluationCase, ...]


EVALUATION_FIXTURES: tuple[EvaluationFixture, ...] = (
    EvaluationFixture(
        "vacancy-cloud-support",
        "vacancy",
        "Vacancy: Remote Cloud Support Engineer",
        "Remote Cloud Support Engineer role working with AWS, Python, FastAPI, PostgreSQL, "
        "Docker, Linux, and incident troubleshooting for customer APIs.",
        (
            EvaluationCase(
                "vacancy-supported-vocab",
                "Explain 'postgresql' in technical English.",
                "A relational database supporting SQL and transactions.",
                "vocabulary",
                "draft",
            ),
            EvaluationCase(
                "vacancy-supported-scaffold",
                "How would you discuss your experience with python?",
                "Practice: I have worked with python to [task]. "
                "Use a truthful example and explain your contribution.",
                "interview_phrase",
                "draft",
                expected_warn_checks=("ambiguity",),
            ),
            EvaluationCase(
                "vacancy-rejected-fabricated-metrics",
                "How did you improve PostgreSQL and API reliability?",
                "I reduced PostgreSQL query latency by 70% and saved $50,000 per year "
                "across 120 production services.",
                "interview_phrase",
                "rejected",
                expected_failed_checks=("technical_accuracy",),
            ),
            EvaluationCase(
                "vacancy-rejected-ungrounded",
                "Explain Kubernetes Helm chart values.",
                "Helm charts package Kubernetes YAML templates and default values.",
                "vocabulary",
                "rejected",
                expected_failed_checks=("source_grounding",),
            ),
            EvaluationCase(
                "vacancy-rejected-low-utility",
                "https://example.com/jobs/cloud-support",
                "12345 !!!",
                "vocabulary",
                "rejected",
                expected_failed_checks=("english_usefulness", "ambiguity", "source_grounding"),
            ),
        ),
    ),
    EvaluationFixture(
        "aws-docs-vpc-iam",
        "aws_docs",
        "AWS Docs: VPC Security & IAM Roles",
        "Amazon VPC security groups act as stateful virtual firewalls for EC2 instances, "
        "while network ACLs are stateless subnet-level filters. IAM roles provide temporary "
        "security credentials for AWS workloads.",
        (
            EvaluationCase(
                "aws-supported-cloze",
                "An Amazon VPC ____ acts as a stateful firewall for EC2 instances.",
                "security group",
                "cloze",
                "draft",
                accepted_answers=("VPC security group",),
            ),
            EvaluationCase(
                "aws-supported-es-en-warn",
                "Traduce al ingles: Los roles de IAM otorgan credenciales temporales.",
                "IAM roles provide temporary security credentials.",
                "es_en",
                "draft",
                expected_warn_checks=("ambiguity",),
            ),
            EvaluationCase(
                "aws-rejected-stateless-sg",
                "How do VPC security groups handle return traffic?",
                "Security groups are stateless firewalls, so return traffic must be allowed.",
                "sentence",
                "rejected",
                expected_failed_checks=("technical_accuracy",),
            ),
            EvaluationCase(
                "aws-rejected-broken-cloze",
                "IAM roles provide temporary security credentials.",
                "temporary credentials",
                "cloze",
                "rejected",
                expected_failed_checks=("ambiguity",),
            ),
        ),
    ),
    EvaluationFixture(
        "interview-networking-star",
        "interview",
        "Interview: Networking & STAR Troubleshooting",
        "Interview prep for cloud troubleshooting: explain the TCP three-way handshake, "
        "DNS resolution, and prepare a STAR story about diagnosing a Linux timeout.",
        (
            EvaluationCase(
                "interview-supported-star",
                "Tell me about a time you diagnosed a Linux timeout.",
                "Use STAR: describe the Situation, Task, Action and Result. "
                "Choose a real experience; do not invent an outcome.",
                "behavioral",
                "draft",
            ),
            EvaluationCase(
                "interview-rejected-tcp-connectionless",
                "Why does TCP use a three-way handshake?",
                "TCP is connectionless and sends packets without establishing a session.",
                "interview_phrase",
                "rejected",
                expected_failed_checks=("technical_accuracy",),
            ),
            EvaluationCase(
                "interview-rejected-identical",
                "Explain DNS resolution during Linux troubleshooting.",
                "Explain DNS resolution during Linux troubleshooting.",
                "interview_phrase",
                "rejected",
                expected_failed_checks=("ambiguity",),
            ),
        ),
    ),
)
