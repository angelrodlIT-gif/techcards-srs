/**
 * Explicit opt-in "Datos demo" and "Peor caso" (break-ui stress test) datasets.
 *
 * Neither mode ever writes to the backend API. Real API data is always the default.
 */

import { addDaysToKey, getLastNDaysKeys, toCancunDateKey } from "./format.js";

export function buildDemoDataset() {
  const today = toCancunDateKey();
  const tomorrow = addDaysToKey(today, 1);
  const nextWeek = addDaysToKey(today, 7);
  const dateKeys = getLastNDaysKeys(84, today);

  // Realistic 12-week pattern for demo inspection
  const heatmapCounts = Object.fromEntries(dateKeys.map((k) => [k, 0]));
  const activeOffsets = [
    [0, 5],
    [1, 8],
    [2, 4],
    [3, 11],
    [4, 6],
    [6, 3],
    [7, 9],
    [9, 4],
    [10, 7],
    [12, 2],
    [14, 12],
    [15, 5],
    [18, 6],
    [21, 8],
    [25, 3],
    [29, 7],
    [34, 4],
    [41, 10],
    [48, 6],
    [55, 5],
    [63, 9],
    [72, 4],
  ];
  for (const [daysAgo, count] of activeOffsets) {
    const k = addDaysToKey(today, -daysAgo);
    if (k in heatmapCounts) heatmapCounts[k] = count;
  }

  const decks = [
    {
      id: "101",
      name: "Cloud & AWS Interviews",
      description: "Arquitectura VPC, IAM, contenedores, observabilidad y trade-offs en inglés técnico.",
    },
    {
      id: "102",
      name: "STAR Behavioral Stories",
      description: "Relatos reales de incidentes, debugging y colaboración remota en 90–120 segundos.",
    },
    {
      id: "103",
      name: "System Design & SQL",
      description: "Transacciones, índices, latencia, colas y diseño resiliente para entrevistas senior.",
    },
  ];

  const cards = [
    {
      id: "1001",
      deck_id: "101",
      front: "Explain the difference between a Security Group and a Network ACL in an AWS VPC.",
      back: "Security Groups are stateful and attach to instances/ENIs (allow rules only); NACLs are stateless, apply at the subnet boundary, and evaluate numbered allow/deny rules in order.",
      kind: "interview_phrase",
      source_label: "template:net-vpc",
      accepted_answers: [
        "Security groups are stateful at the instance level; NACLs are stateless at the subnet level.",
      ],
      explanation: "Conecta el concepto con un caso de troubleshooting real (p. ej. puertos efímeros bloqueados en NACL).",
      error_id: null,
      repetitions: 1,
      interval_days: 1,
      ease_factor: 2.5,
      due_date: today,
    },
    {
      id: "1002",
      deck_id: "101",
      front: "In a private subnet, outbound internet traffic for OS patches is routed through a ____.",
      back: "NAT Gateway",
      kind: "cloze",
      source_label: "AWS VPC Docs",
      accepted_answers: ["NAT gateway", "NAT instance"],
      explanation: "Recuerda contrastar NAT Gateway (salida desde subred privada) con Internet Gateway (tráfico bidireccional público).",
      error_id: null,
      repetitions: 3,
      interval_days: 12,
      ease_factor: 2.6,
      due_date: nextWeek,
    },
    {
      id: "1003",
      deck_id: "101",
      front: "Correct: The deployment depends of the Terraform state lock.",
      back: "The deployment depends on the Terraform state lock.",
      kind: "interview_phrase",
      source_label: "error:502",
      accepted_answers: ["It depends on the Terraform state lock."],
      explanation: "[Technical remediation] Fixes: 'depends of' -> 'depends on'.",
      error_id: "502",
      repetitions: 0,
      interval_days: 0,
      ease_factor: 2.5,
      due_date: today,
    },
    {
      id: "1004",
      deck_id: "101",
      front: "Explain how DNS resolves a domain name and how TTL affects cutovers.",
      back: "Local cache -> recursive resolver -> root -> TLD -> authoritative nameserver. Lowering TTL before a migration shortens stale-cache windows at the cost of more lookups.",
      kind: "interview_phrase",
      source_label: "template:net-dns",
      accepted_answers: [],
      explanation: "Nombra cada salto en orden y menciona cuándo bajar el TTL antes de cambiar un registro.",
      error_id: null,
      repetitions: 2,
      interval_days: 6,
      ease_factor: 2.5,
      due_date: tomorrow,
    },
    {
      id: "1005",
      deck_id: "102",
      front: "STAR speaking prompt: Describe a real technical outage you diagnosed and resolved.",
      back: "Situation: real service & symptom.\nTask: your exact ownership & constraints.\nAction: concrete logs/metrics checked and fix applied.\nResult: honest outcome and prevention follow-up.",
      kind: "behavioral",
      source_label: "template:star-troubleshooting",
      accepted_answers: [],
      explanation: "Mantén 90–120 s con hechos reales, sin inflar alcance ni métricas.",
      error_id: null,
      repetitions: 1,
      interval_days: 1,
      ease_factor: 2.4,
      due_date: today,
    },
    {
      id: "1006",
      deck_id: "102",
      front: "Cómo dirías en inglés: 'Alineemos el alcance antes de comprometernos con una fecha.'",
      back: "Let's align on the scope before committing to a timeline.",
      kind: "es_en",
      source_label: "Remote Standup Notes",
      accepted_answers: ["Let's agree on scope before we commit to a deadline."],
      explanation: "'Align on scope' suena natural y ejecutivo en equipos remotos.",
      error_id: null,
      repetitions: 3,
      interval_days: 14,
      ease_factor: 2.65,
      due_date: nextWeek,
    },
    {
      id: "1007",
      deck_id: "103",
      front: "Explain why SELECT ... FOR UPDATE prevents lost updates under concurrent transactions.",
      back: "It acquires a row-level lock on matched rows until COMMIT or ROLLBACK, serializing concurrent writers so later transactions read the committed state.",
      kind: "vocabulary",
      source_label: "PostgreSQL Concurrency",
      accepted_answers: [],
      explanation: "Menciona el orden de bloqueo para evitar deadlocks entre dos filas.",
      error_id: null,
      repetitions: 4,
      interval_days: 19,
      ease_factor: 2.7,
      due_date: nextWeek,
    },
  ];

  const templates = [
    {
      id: "star-troubleshooting",
      category: "star",
      title: "STAR: Diagnosing a Real Technical Issue",
      kind: "behavioral",
      front:
        "STAR speaking prompt: Describe a real technical issue or outage you diagnosed and resolved. Use only a real experience—do not invent achievements, roles, or metrics.",
      back: "Truthful STAR scaffold:\n- Situation: Real system, context, and symptom.\n- Task: Your actual responsibility and constraints.\n- Action: Concrete debugging steps and fix you executed.\n- Result: Honest outcome and what you learned.",
      follow_up_questions: [],
      explanation: "Speak 90–120s using only real facts; never fabricate metrics or ownership.",
    },
    {
      id: "net-vpc",
      category: "networking",
      title: "Explain VPC (Virtual Private Cloud)",
      kind: "interview_phrase",
      front:
        "Explain what a VPC (Virtual Private Cloud) is and how traffic enters and leaves it. Follow-ups: (1) How do public and private subnets differ? (2) When do you use an Internet Gateway vs. a NAT Gateway?",
      back: "Key points: isolated virtual network with a CIDR block split into subnets; route tables direct traffic; IGW gives direct public access, NAT Gateway enables outbound traffic from private subnets; security groups (stateful) and NACLs (stateless).",
      follow_up_questions: [
        "How do public and private subnets differ?",
        "When do you use an Internet Gateway vs. a NAT Gateway?",
      ],
      explanation: "Answer the core explanation first, then each follow-up aloud.",
    },
    {
      id: "net-dns",
      category: "networking",
      title: "Explain DNS Resolution",
      kind: "interview_phrase",
      front:
        "Explain how DNS resolves a domain name to an IP address. Follow-ups: (1) How do A, AAAA, and CNAME records differ? (2) How does TTL affect DNS changes and troubleshooting?",
      back: "Key points: local cache -> recursive resolver -> root -> TLD -> authoritative nameserver, cached per TTL; A maps IPv4, AAAA maps IPv6, CNAME aliases hostnames; lower TTL speeds cutovers at the cost of extra lookups.",
      follow_up_questions: [
        "How do A, AAAA, and CNAME records differ?",
        "How does TTL affect DNS changes and troubleshooting?",
      ],
      explanation: "Walk the resolution path step by step before answering the follow-ups.",
    },
  ];

  const sources = [
    {
      id: "301",
      label: "AWS Well-Architected Reliability Pillar",
      url: "https://example.org/docs/reliability-pillar/failure-isolation",
      normalized_url: "https://example.org/docs/reliability-pillar/failure-isolation",
      excerpt: "Bulkheads isolate failures to a single availability zone or cell so blast radius stays bounded.",
      status: "draft",
    },
    {
      id: "302",
      label: "PostgreSQL Locking Docs",
      url: "https://example.org/postgres/explicit-locking",
      normalized_url: "https://example.org/postgres/explicit-locking",
      excerpt: "Row-level locks do not block readers; they serialize writers targeting the same row.",
      status: "approved",
    },
    {
      id: "303",
      label: "Old interview blog snippet",
      url: null,
      normalized_url: null,
      excerpt: "Duplicate notes already covered in networking templates.",
      status: "discarded",
    },
  ];

  const errors = [
    {
      id: "501",
      attempted: "The health check did not responded in Monday during the cutover.",
      corrected: "The health check did not respond on Monday during the cutover.",
      rationale: "[Technical remediation] Fixes: 'did not responded' -> 'did not respond'; 'in monday' -> 'on Monday'.",
      status: "draft",
      card_id: null,
    },
    {
      id: "502",
      attempted: "The deployment depends of the Terraform state lock.",
      corrected: "The deployment depends on the Terraform state lock.",
      rationale: "[Technical remediation] Fixes: 'depends of' -> 'depends on'.",
      status: "approved",
      card_id: "1003",
    },
    {
      id: "503",
      attempted: "I am agree with moving the cache to Redis.",
      corrected: "I agree with moving the cache to Redis.",
      rationale: "[Technical remediation] Fixes: 'i am agree' -> 'I agree'.",
      status: "discarded",
      card_id: null,
    },
  ];

  const analytics = {
    semantics_version: 1,
    date_timezone: "America/Cancun",
    start: null,
    end: null,
    reviews: {
      recall: { numerator: 112, denominator: 132 },
      lapse: { numerator: 9, denominator: 98 },
    },
    practice: {
      sessions: 22,
      first_review_at: `${addDaysToKey(today, -72)}T14:15:00Z`,
      last_review_at: `${today}T16:40:00Z`,
      first_review_cancun_date: addDaysToKey(today, -72),
      last_review_cancun_date: today,
      observed_span_seconds: 5820,
      active_study_seconds: null,
      response_seconds: null,
    },
    error_correction: {
      current_drafts: 1,
      current_discarded: 1,
      current_approved: 1,
      current_approved_without_card: 0,
      first_review_recall: { numerator: 4, denominator: 5 },
    },
    data_quality: {
      reviews_without_timestamp: 0,
      reviews_with_invalid_grade: 0,
      possible_duplicate_reviews: 0,
    },
  };

  return { decks, cards, templates, sources, errors, analytics, heatmapCounts };
}

/**
 * Worst-case stress-test fixture following break-ui/CATALOG.md:
 * - IDs beyond Number.MAX_SAFE_INTEGER (64-bit / 19-digit)
 * - Long hyphenated/diacritic/CJK/RTL/emoji deck names & 1-letter deck name
 * - Unbreakable URLs, raw HTML/script escaping payloads, 2,000-char card text
 * - 0 cards, 1 card (pluralization), and 10,000 cards virtual count deck
 */
export function buildWorstCaseDataset() {
  const today = toCancunDateKey();
  const dateKeys = getLastNDaysKeys(84, today);
  const heatmapCounts = Object.fromEntries(dateKeys.map((k) => [k, 0]));
  heatmapCounts[today] = 1;

  const decks = [
    {
      id: "9007199254740993123",
      name: "Aleksandra Wiśniewska-Kowalczyk · Benachrichtigungseinstellungen & Paramètres de confidentialité et de sécurité",
      description:
        "URL sin espacios: https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved — Escaping test: <script>alert(1)</script> &amp; **bold**",
    },
    {
      id: "9007199254740993124",
      name: "👩🏽‍💻 Priya · Đặng Thị Ngọc Hân · نور الهدى عبد الرحمن · 王秀英",
      description: "",
    },
    {
      id: "9007199254740993125",
      name: "J",
      description: "Un solo carácter y exactamente 1 tarjeta pendiente (prueba de plurales).",
    },
    {
      id: "9007199254740993126",
      name: "Mazo masivo (10,000 tarjetas simuladas)",
      description: "Prueba de conteo masivo, números tabulares y render paginado sin congelar el navegador.",
      _syntheticTotalCards: 10000,
      _syntheticDueCards: 1284,
      _syntheticMasteredCards: 6420,
    },
    {
      id: "9007199254740993127",
      name: "Mazo vacío (0 tarjetas)",
      description: "Comprueba división por cero, barras vacías y estado sin tarjetas.",
    },
  ];

  const longParagraph =
    "Walk through a real distributed-systems incident involving bartholomew.fitzgerald@northwind-industries-holdings.example.com and https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved. " +
    "Explain root cause, blast radius containment, DNS TTL propagation, TCP SYN timeout vs RST, and PostgreSQL row-level locking without fabricating metrics. ".repeat(
      8
    );

  const cards = [
    {
      id: "18446744073709551601",
      deck_id: "9007199254740993123",
      front: longParagraph,
      back: "Structured response with <script>alert('xss')</script> escaped safely &amp; clear trade-offs.\n- Situation: real multi-region API timeout.\n- Action: isolated noisy neighbor and lowered DNS TTL.",
      kind: "behavioral",
      source_label: "customer-feedback-from-enterprise-onboarding-very-long-label-v12",
      accepted_answers: [
        "bartholomew.fitzgerald@northwind-industries-holdings.example.com",
        "<b>literal html</b>",
        "Answer 3",
        "Answer 4",
      ],
      explanation: "Prueba de tarjeta extensa con diacritics (Đặng Thị Ngọc Hân) y texto largo al 200% zoom.",
      error_id: "9007199254740999001",
      repetitions: 1,
      interval_days: 1,
      ease_factor: 2.5000000001,
      due_date: today,
    },
    {
      id: "18446744073709551602",
      deck_id: "9007199254740993125",
      front: "When a TCP port is closed and actively rejects connections, the host replies with ____.",
      back: "RST",
      kind: "cloze",
      source_label: null,
      accepted_answers: [],
      explanation: null,
      error_id: null,
      repetitions: 0,
      interval_days: 0,
      ease_factor: 2.5,
      due_date: today,
    },
    {
      id: "18446744073709551603",
      deck_id: "9007199254740993124",
      front: "🦊 Fox · Đặng Thị Ngọc Hân · نور الهدى — Explain zero-downtime schema migrations.",
      back: "Expand-and-contract pattern: add nullable column, dual-write, backfill, switch reads, drop old column.",
      kind: "interview_phrase",
      source_label: "IMG_20250914_183022_HDR_portrait_edited_edited.HEIC",
      accepted_answers: [],
      explanation: "Verifica que diacríticos altos, emoji ZWJ y RTL no se recorten ni desalineen el layout.",
      error_id: null,
      repetitions: 2,
      interval_days: 6,
      ease_factor: 2.6,
      due_date: today,
    },
  ];

  // Add 120 realistic cards to the massive deck so card-browser pagination/chunking is exercised
  for (let i = 1; i <= 120; i += 1) {
    cards.push({
      id: `18446744073709552${String(i).padStart(3, "0")}`,
      deck_id: "9007199254740993126",
      front: `Card #${i}: Explain trade-off #${i} in cloud networking & observability.`,
      back: `Reference summary for scenario #${i} with concrete telemetry checks.`,
      kind: i % 2 === 0 ? "interview_phrase" : "vocabulary",
      source_label: i % 3 === 0 ? "massive-import" : null,
      accepted_answers: [],
      explanation: null,
      error_id: null,
      repetitions: i % 3 === 0 ? 3 : 0,
      interval_days: i % 3 === 0 ? 12 : 0,
      ease_factor: 2.5,
      due_date: today,
    });
  }

  const templates = buildDemoDataset().templates;

  const sources = [
    {
      id: "9007199254740998001",
      label: "Q3 Board Deck — FINAL (revised) v12 [approved by legal].pdf · <script>alert(1)</script>",
      url: "https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved&token=9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f",
      normalized_url:
        "https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved&token=9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f",
      excerpt: longParagraph,
      status: "draft",
    },
    {
      id: "9007199254740998002",
      label: "a",
      url: null,
      normalized_url: null,
      excerpt: null,
      status: "approved",
    },
  ];

  const errors = [
    {
      id: "9007199254740999001",
      attempted:
        "Prompt: bartholomew.fitzgerald@northwind-industries-holdings.example.com\nAnswer: <script>alert(1)</script> The service did not responded in Monday and depends of DNS TTL.",
      corrected:
        "The service did not respond on Monday and depends on DNS TTL. (Đặng Thị Ngọc Hân · نور الهدى)",
      rationale: "[Technical remediation] Benachrichtigungseinstellungen · 9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f",
      status: "draft",
      card_id: null,
    },
    {
      id: "9007199254740999002",
      attempted: "J",
      corrected: "Concise approved phrase",
      rationale: "[STAR remediation] Missing STAR elements: Result.",
      status: "approved",
      card_id: "18446744073709551601",
    },
    {
      id: "9007199254740999003",
      attempted: "Discarded with &amp; **markdown** literal text",
      corrected: "Literal text stays escaped",
      rationale: "No mechanical phrasing issue detected.",
      status: "discarded",
      card_id: null,
    },
  ];

  const analytics = {
    semantics_version: 1,
    date_timezone: "America/Cancun",
    start: null,
    end: null,
    reviews: {
      recall: { numerator: 1, denominator: 1 },
      lapse: { numerator: 0, denominator: 0 },
    },
    practice: {
      sessions: 1,
      first_review_at: `${today}T12:00:00Z`,
      last_review_at: `${today}T12:00:00Z`,
      first_review_cancun_date: today,
      last_review_cancun_date: today,
      observed_span_seconds: 4622400, // 1,284 hours -> tests day roll-up
      active_study_seconds: null,
      response_seconds: null,
    },
    error_correction: {
      current_drafts: 1284,
      current_discarded: 1,
      current_approved: 10000,
      current_approved_without_card: 3,
      first_review_recall: { numerator: 0, denominator: 0 },
    },
    data_quality: {
      reviews_without_timestamp: 2,
      reviews_with_invalid_grade: 1,
      possible_duplicate_reviews: 4,
    },
  };

  return { decks, cards, templates, sources, errors, analytics, heatmapCounts };
}
