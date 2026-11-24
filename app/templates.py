"""Read-only catalog of generic STAR speaking scaffolds and networking explain prompts."""

from dataclasses import dataclass

from app.schemas import Kind, TemplateCategory


@dataclass(frozen=True)
class StudyTemplate:
    id: str
    category: TemplateCategory
    title: str
    kind: Kind
    front: str
    back: str
    follow_up_questions: tuple[str, ...] = ()
    explanation: str | None = None


STUDY_TEMPLATES: tuple[StudyTemplate, ...] = (
    StudyTemplate(
        id="star-troubleshooting",
        category="star",
        title="STAR: Diagnosing a Real Technical Issue",
        kind="behavioral",
        front=(
            "STAR speaking prompt: Describe a real technical issue or outage you diagnosed and "
            "resolved. Use only a real experience—do not invent achievements, roles, or metrics."
        ),
        back=(
            "Truthful STAR scaffold (real experience only; never invent achievements):\n"
            "- Situation: Real system, context, and symptom.\n"
            "- Task: Your actual responsibility and constraints.\n"
            "- Action: Concrete debugging steps and fix you executed.\n"
            "- Result: Honest outcome and what you learned."
        ),
        explanation="Speak 90–120s using only real facts; never fabricate metrics or ownership.",
    ),
    StudyTemplate(
        id="star-collaboration",
        category="star",
        title="STAR: Explaining a Technical Trade-off or Blocker",
        kind="behavioral",
        front=(
            "STAR speaking prompt: Describe a real situation where you explained a technical "
            "blocker or trade-off to a teammate, manager, or user. Use only a real experience—"
            "do not invent achievements."
        ),
        back=(
            "Truthful STAR scaffold (real experience only; never invent achievements):\n"
            "- Situation: Real project context and audience.\n"
            "- Task: Decision or risk to communicate clearly.\n"
            "- Action: Options, trade-offs, and next steps you presented.\n"
            "- Result: Actual decision reached and honest takeaway."
        ),
        explanation="State your real role concisely without inflating scope or impact.",
    ),
    StudyTemplate(
        id="net-vpc",
        category="networking",
        title="Explain VPC (Virtual Private Cloud)",
        kind="interview_phrase",
        front=(
            "Explain what a VPC (Virtual Private Cloud) is and how traffic enters and leaves it. "
            "Follow-ups: (1) How do public and private subnets differ? "
            "(2) When do you use an Internet Gateway vs. a NAT Gateway?"
        ),
        back=(
            "Key points: isolated virtual network with a CIDR block split into subnets; route "
            "tables direct traffic; IGW gives direct public access, NAT Gateway enables outbound "
            "traffic from private subnets; security groups (stateful) and NACLs (stateless)."
        ),
        follow_up_questions=(
            "How do public and private subnets differ?",
            "When do you use an Internet Gateway vs. a NAT Gateway?",
        ),
        explanation="Answer the core explanation first, then each follow-up aloud.",
    ),
    StudyTemplate(
        id="net-subnetting",
        category="networking",
        title="Explain Subnetting and CIDR",
        kind="interview_phrase",
        front=(
            "Explain subnetting and CIDR notation (e.g., /24 vs. /26) in plain English. "
            "Follow-ups: (1) Why split a network into smaller subnets? "
            "(2) Why are not all addresses in a subnet usable by hosts?"
        ),
        back=(
            "Key points: CIDR prefix splits network vs. host bits; smaller subnets isolate "
            "routing/broadcast domains and separate public/private tiers; network, broadcast, "
            "and cloud-reserved addresses reduce usable host count."
        ),
        follow_up_questions=(
            "Why split a network into smaller subnets?",
            "Why are not all addresses in a subnet usable by hosts?",
        ),
        explanation="State the bit split clearly and walk through one host-count example.",
    ),
    StudyTemplate(
        id="net-dns",
        category="networking",
        title="Explain DNS Resolution",
        kind="interview_phrase",
        front=(
            "Explain how DNS resolves a domain name to an IP address. "
            "Follow-ups: (1) How do A, AAAA, and CNAME records differ? "
            "(2) How does TTL affect DNS changes and troubleshooting?"
        ),
        back=(
            "Key points: local cache -> recursive resolver -> root -> TLD -> authoritative "
            "nameserver, cached per TTL; A maps IPv4, AAAA maps IPv6, CNAME aliases hostnames; "
            "lower TTL speeds cutovers at the cost of extra lookups."
        ),
        follow_up_questions=(
            "How do A, AAAA, and CNAME records differ?",
            "How does TTL affect DNS changes and troubleshooting?",
        ),
        explanation="Walk the resolution path step by step before answering the follow-ups.",
    ),
    StudyTemplate(
        id="net-tcp-handshake",
        category="networking",
        title="Explain the TCP Three-Way Handshake",
        kind="interview_phrase",
        front=(
            "Explain the TCP three-way handshake and why it exists. "
            "Follow-ups: (1) What does a SYN timeout vs. RST indicate? "
            "(2) How does TCP differ from UDP when troubleshooting?"
        ),
        back=(
            "Key points: SYN -> SYN-ACK -> ACK synchronizes sequence numbers for reliable ordered "
            "delivery; SYN timeout points to firewall drop or routing issue, RST to closed port "
            "or active rejection; TCP guarantees delivery/order unlike UDP."
        ),
        follow_up_questions=(
            "What does a SYN timeout vs. RST indicate?",
            "How does TCP differ from UDP when troubleshooting?",
        ),
        explanation="Connect each handshake step to a concrete troubleshooting symptom.",
    ),
)

TEMPLATES_BY_ID: dict[str, StudyTemplate] = {t.id: t for t in STUDY_TEMPLATES}
