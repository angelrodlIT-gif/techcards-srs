"""Replace get_generator via dependency injection to add a hosted LLM strategy."""

import re
from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings
from app.schemas import Kind


@dataclass(frozen=True)
class GeneratedCard:
    front: str
    back: str
    kind: Kind


class CardGenerator(Protocol):
    def generate(self, text: str, max_cards: int) -> list[GeneratedCard]: ...


GLOSSARY = {
    "aws": "Amazon Web Services: a cloud platform offering compute, storage and networking.",
    "python": "A programming language commonly used for APIs, automation and data processing.",
    "postgresql": "A relational database supporting SQL and transactions.",
    "docker": "A tool for packaging applications and dependencies in containers.",
    "linux": "An operating system commonly used to run cloud servers.",
    "terraform": "An infrastructure-as-code tool for declaring and provisioning resources.",
    "monitoring": "Observing system metrics, logs and events to detect problems.",
    "troubleshooting": "Investigating symptoms to identify and resolve a system problem.",
    "api": "Application programming interface: a contract for software communication.",
    "sql": "Structured Query Language: a language for querying relational databases.",
}


class MockGenerator:
    def generate(self, text: str, max_cards: int) -> list[GeneratedCard]:
        words = set(re.findall(r"[a-z]+", text.lower()))
        terms = [term for term in GLOSSARY if term in words]
        cards = [
            GeneratedCard(f"Explain '{term}' in technical English.", GLOSSARY[term], "vocabulary")
            for term in terms
        ]
        # Templates are practice prompts, never claims about the learner's experience.
        topic = terms[0] if terms else "the technical responsibilities in this text"
        cards.extend(
            [
                GeneratedCard(
                    f"How would you discuss your experience with {topic}?",
                    f"Practice: I have worked with {topic} to [task]. "
                    "Use a truthful example and explain your contribution.",
                    "interview_phrase",
                ),
                GeneratedCard(
                    f"Tell me about a time you solved a problem involving {topic}.",
                    "Use STAR: describe the Situation, Task, Action and Result. "
                    "Choose a real experience; do not invent an outcome.",
                    "behavioral",
                ),
            ]
        )
        return cards[:max_cards]


def get_generator() -> CardGenerator:
    get_settings()  # Reject unsupported provider configuration rather than silently ignoring it.
    return MockGenerator()
