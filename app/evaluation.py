"""Conservative, offline checks for generated study material."""

import re

from app.generator import GLOSSARY
from app.schemas import CLOZE_BLANK_RE, MAX_LISTENING_CHARS, CardEvaluationOut, Kind

SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
WORD = re.compile(r"\b[a-z][a-z0-9]*\b")
NUMBER = re.compile(r"(?<!\w)\d+(?:,\d{3})*(?:\.\d+)?")
CLAIM = re.compile(
    r"\b(?:i|we)(?: have|'ve)? (?:led|built|designed|architected|migrated|"
    r"reduced|improved|increased|cut|saved|managed|owned|maintained|deployed|"
    r"automated|created|implemented|developed|resolved|fixed|troubleshot|configured|"
    r"optimized|scaled|delivered|launched|supported|administered|operated|monitored|"
    r"wrote|authored|spearheaded|drove|achieved|eliminated|prevented|handled|worked)\b"
)
PLACEHOLDER = re.compile(r"\[[^\[\]\n]+\]")
UNRESOLVED = re.compile(r"\b(?:todo|tbd)\b|\?{3}")
URL = re.compile(r"https?://\S+")
FALLBACK_TOPIC = "the technical responsibilities in this text"
PRACTICE = re.compile(
    r"practice: i have worked with ([a-z][a-z0-9+-]*) to "
    r"\[task\]\. use a truthful example(?: and explain your contribution)?"
)
STAR = (
    "use star: describe the situation, task, action and result. "
    "choose a real experience; do not invent an outcome"
)
CONTRADICTION = re.compile(
    r"\b(?:security groups? (?:is|are) stateless|"
    r"(?:network acls?|nacls?) (?:is|are) stateful|"
    r"tcp is (?:connectionless|unreliable)|"
    r"udp is (?:connection-oriented|reliable)|udp uses (?:a |the )?(?:three|3)[ -]way handshake|"
    r"iam roles? (?:uses?|provides?) (?:permanent|static|long-term) credentials|"
    r"(?:postgresql|sql) is (?:a )?nosql|docker is (?:a )?(?:relational )?database|"
    r"python is (?:an? )?(?:operating system|database)|"
    r"linux is (?:a )?(?:programming language|database)|"
    r"terraform is (?:a )?(?:programming language|database))\b"
)


def normalize(value: str) -> str:
    value = " ".join(value.casefold().replace("’", "'").split())
    value = NUMBER.sub(lambda match: match[0].replace(",", ""), value)
    return re.sub(r"(?<=\$) (?=\d)|(?<=\d) (?=%)", "", value)


def evaluate_generated_card(
    *,
    front: str,
    back: str,
    kind: Kind,
    source_text: str,
    accepted_answers: list[str] | tuple[str, ...] = (),
    explanation: str | None = None,
) -> CardEvaluationOut:
    normalized_front = normalize(front)
    source = normalize(source_text)
    sentences = {normalize(sentence).rstrip(".") for sentence in SENTENCE_END.split(source_text)}
    sentences.add(source.rstrip("."))
    source_words = set(WORD.findall(source))
    topics = {word for word in WORD.findall(normalized_front) if len(word) > 1} & source_words
    definitions = {normalize(GLOSSARY[term]).rstrip(".") for term in topics & GLOSSARY.keys()}
    grounded_answers = sentences | definitions
    failures: dict[str, str] = {}
    ambiguity_warning = kind in {"cloze", "es_en"} and not accepted_answers
    uncertainty = ["Offline checks cover a limited set of contradictions and use lexical evidence."]

    if kind == "cloze" and CLOZE_BLANK_RE.findall(front) != ["____"]:
        failures["ambiguity"] = "Cloze prompts need exactly one ____ blank."
    for label, raw in [
        ("front", front),
        ("back", back),
        *((f"accepted_answers[{index}]", raw) for index, raw in enumerate(accepted_answers)),
        *([("explanation", explanation)] if explanation is not None else []),
    ]:
        value = normalize(raw)
        evidence = value.rstrip(".")
        is_answer = label == "back" or label.startswith("accepted_answers")
        words = WORD.findall(URL.sub("", value))
        practice = PRACTICE.fullmatch(evidence) if label == "back" else None
        scaffold = (
            kind == "interview_phrase" and practice is not None and practice[1] in topics
        ) or (label == "back" and kind == "behavioral" and evidence == STAR and bool(topics))

        min_words = 1 if is_answer and kind == "cloze" else 2
        max_length = MAX_LISTENING_CHARS if label == "back" and kind == "listening" else 5000
        if (
            "\x00" in raw
            or len(raw) > max_length
            or len(words) < min_words
            or not any(len(word) > 1 for word in words)
        ):
            failures.setdefault("english_usefulness", f"{label} needs usable English text.")
        if UNRESOLVED.search(value) or (
            label != "front" and value.rstrip(".!?") == normalized_front.rstrip(".!?")
        ):
            failures.setdefault("ambiguity", f"{label} repeats the prompt or is unfinished.")
        if PLACEHOLDER.search(value) and not scaffold:
            failures.setdefault("ambiguity", f"{label} contains an unresolved placeholder.")
        if scaffold:
            ambiguity_warning = True
            uncertainty.append("Use a truthful personal example for this practice scaffold.")

        if FALLBACK_TOPIC in value:
            failures.setdefault("source_grounding", f"{label} uses a generic fallback topic.")
        if kind == "cloze":
            if label == "front":
                continue  # The completed prompt is checked with every answer.
            if is_answer:
                evidence = normalized_front.replace("____", evidence, 1).rstrip(".")
        if CONTRADICTION.search(evidence):
            failures.setdefault("technical_accuracy", f"{label} contains a known contradiction.")
        if (
            not scaffold
            and evidence not in sentences
            and (CLAIM.search(evidence) or NUMBER.search(evidence))
        ):
            failures.setdefault(
                "technical_accuracy",
                f"{label} contains a claim or metric without matching source wording.",
            )
        if label != "front" and not scaffold and evidence not in grounded_answers:
            failures.setdefault(
                "source_grounding", f"{label} needs wording supported by the source."
            )
        if label != "front" and evidence in definitions and evidence not in sentences:
            warning = "The answer relies on a built-in glossary definition."
            if warning not in uncertainty:
                uncertainty.append(warning)

    if kind in {"cloze", "es_en"} and not accepted_answers:
        uncertainty.append("Review whether alternative answers are needed.")

    checks = dict.fromkeys(
        ("english_usefulness", "technical_accuracy", "ambiguity", "source_grounding"), "pass"
    )
    if ambiguity_warning:
        checks["ambiguity"] = "warn"
    checks.update(dict.fromkeys(failures, "fail"))
    return CardEvaluationOut(
        status="rejected" if failures else "draft",
        ready_for_review=not failures,
        checks=checks,
        uncertainty=uncertainty,
        rejection_reasons=list(failures.values()),
    )
