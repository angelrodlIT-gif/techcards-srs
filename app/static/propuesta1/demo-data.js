/**
 * Explicit read-only synthetic datasets for "Datos demo" and `break-ui` stress testing.
 * NEVER writes to the real FastAPI backend.
 */

export function buildDemoDataset() {
  const today = new Date().toISOString().slice(0, 10);
  const decks = [
    {
      id: "101",
      name: "Cloud Interviews · AWS & Networking",
      description: "Preguntas técnicas de VPC, DNS, TCP y arquitectura en inglés técnico para entrevistas remotas.",
    },
    {
      id: "102",
      name: "Behavioral STAR Stories",
      description: "Escenarios reales estructurados con Situation, Task, Action y Result sin inflar logros.",
    },
    {
      id: "103",
      name: "Backend & PostgreSQL Vocabulary",
      description: "Vocabulario preciso de transacciones, locks, índices y APIs REST.",
    },
  ];

  const cards = [
    {
      id: "1001",
      deck_id: "101",
      front: "Explain what a VPC (Virtual Private Cloud) is and when you use an Internet Gateway vs. a NAT Gateway.",
      back: "A VPC is an isolated virtual network with a CIDR block split into subnets. An Internet Gateway enables bidirectional public internet access for public subnets; a NAT Gateway lets instances in private subnets initiate outbound internet traffic without accepting unsolicited inbound connections.",
      kind: "interview_phrase",
      source_label: "template:net-vpc",
      accepted_answers: ["IGW for public subnets, NAT Gateway for outbound-only private subnets"],
      explanation: "Responde primero la diferencia de dirección de tráfico y menciona tablas de rutas y security groups.",
      error_id: null,
      repetitions: 2,
      interval_days: 6,
      ease_factor: 2.5,
      due_date: today,
    },
    {
      id: "1002",
      deck_id: "101",
      front: "In TCP troubleshooting, a SYN timeout usually indicates ____ whereas a RST points to a closed port or active rejection.",
      back: "a firewall drop or routing issue",
      kind: "cloze",
      source_label: "AWS Networking Notes",
      accepted_answers: ["packet drop by a firewall", "routing blackhole or security group drop"],
      explanation: "Contrasta silencio (timeout = drop silencioso) frente a rechazo explícito (RST).",
      error_id: null,
      repetitions: 0,
      interval_days: 0,
      ease_factor: 2.5,
      due_date: today,
    },
    {
      id: "1003",
      deck_id: "101",
      front: "Correct: The health check did not responded in Monday because the timeout depends of the load balancer.",
      back: "The health check did not respond on Monday because the timeout depends on the load balancer.",
      kind: "interview_phrase",
      source_label: "error:501",
      accepted_answers: [],
      explanation: "[Technical remediation] Fixes: 'did not responded' -> 'did not respond'; 'in monday' -> 'on Monday'; 'depends of' -> 'depends on'.",
      error_id: "501",
      repetitions: 1,
      interval_days: 1,
      ease_factor: 2.36,
      due_date: today,
    },
    {
      id: "1004",
      deck_id: "102",
      front: "Tell me about a real technical outage you diagnosed and resolved without inventing metrics.",
      back: "Situation: Local Postgres lock contention stalled review writes.\nTask: Isolate the blocking query and restore atomic updates.\nAction: Added SELECT ... FOR UPDATE and verified concurrency with tests.\nResult: Eliminated lost updates and documented the troubleshooting runbook.",
      kind: "behavioral",
      source_label: "template:star-troubleshooting",
      accepted_answers: [],
      explanation: "Habla entre 90 y 120 segundos usando solo hechos verificables.",
      error_id: null,
      repetitions: 3,
      interval_days: 15,
      ease_factor: 2.6,
      due_date: "2099-01-01",
    },
    {
      id: "1005",
      deck_id: "103",
      front: "Traduce al inglés técnico: «La migración es idempotente y se ejecuta dentro de una transacción.»",
      back: "The migration is idempotent and runs inside a transaction.",
      kind: "es_en",
      source_label: "PostgreSQL Docs",
      accepted_answers: ["The migration is idempotent and executes within a transaction."],
      explanation: "Usa 'runs inside a transaction' o 'executes within a transaction' en tono natural.",
      error_id: null,
      repetitions: 0,
      interval_days: 0,
      ease_factor: 2.5,
      due_date: today,
    },
  ];

  const templates = [
    {
      id: "star-troubleshooting",
      category: "star",
      title: "STAR: Diagnosing a Real Technical Issue",
      kind: "behavioral",
      front: "STAR speaking prompt: Describe a real technical issue or outage you diagnosed and resolved. Use only a real experience—do not invent achievements, roles, or metrics.",
      back: "Truthful STAR scaffold (real experience only; never invent achievements):\n- Situation: Real system, context, and symptom.\n- Task: Your actual responsibility and constraints.\n- Action: Concrete debugging steps and fix you executed.\n- Result: Honest outcome and what you learned.",
      follow_up_questions: [],
      explanation: "Speak 90–120s using only real facts; never fabricate metrics or ownership.",
    },
    {
      id: "net-vpc",
      category: "networking",
      title: "Explain VPC (Virtual Private Cloud)",
      kind: "interview_phrase",
      front: "Explain what a VPC (Virtual Private Cloud) is and how traffic enters and leaves it.",
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
      front: "Explain how DNS resolves a domain name to an IP address.",
      back: "Key points: local cache -> recursive resolver -> root -> TLD -> authoritative nameserver, cached per TTL; A maps IPv4, AAAA maps IPv6, CNAME aliases hostnames.",
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
      label: "AWS VPC User Guide — NAT Gateways",
      url: "https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html",
      normalized_url: "https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html",
      excerpt: "You can use a NAT gateway so that instances in a private subnet can connect to services outside your VPC but external services cannot initiate a connection.",
      status: "draft",
    },
    {
      id: "302",
      label: "PostgreSQL Explicit Locking",
      url: "https://www.postgresql.org/docs/current/explicit-locking.html",
      normalized_url: "https://www.postgresql.org/docs/current/explicit-locking.html",
      excerpt: "FOR UPDATE causes the rows retrieved by the SELECT statement to be locked as though for update.",
      status: "approved",
    },
  ];

  const errors = [
    {
      id: "501",
      attempted: "The health check did not responded in Monday because the timeout depends of the load balancer.",
      corrected: "The health check did not respond on Monday because the timeout depends on the load balancer.",
      rationale: "[Technical remediation] Fixes: 'did not responded' -> 'did not respond'; 'in monday' -> 'on Monday'; 'depends of' -> 'depends on'.",
      status: "approved",
      card_id: "1003",
    },
    {
      id: "502",
      attempted: "Prompt: Explain why you chose a private subnet.\nAnswer: I am agree that private subnets depend of NAT for updates.",
      corrected: "I agree that private subnets depend on a NAT Gateway for outbound updates.",
      rationale: "[Technical remediation] Fixes: 'i am agree' -> 'I agree'; 'depend of' -> 'depend on'. Offline heuristic requires human review.",
      status: "draft",
      card_id: null,
    },
    {
      id: "503",
      attempted: "I restarted the server and it worked.",
      corrected: "Truthful STAR scaffold: add Situation, Task, Action and Result.",
      rationale: "[STAR remediation] Missing STAR elements: Situation, Task, Action, Result.",
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
      recall: { numerator: 17, denominator: 21 },
      lapse: { numerator: 2, denominator: 14 },
    },
    practice: {
      sessions: 4,
      first_review_at: "2026-11-20T15:10:00Z",
      last_review_at: "2026-11-26T22:40:00Z",
      first_review_cancun_date: "2026-11-20",
      last_review_cancun_date: "2026-11-26",
      observed_span_seconds: 1840,
      active_study_seconds: null,
      response_seconds: null,
    },
    error_correction: {
      current_drafts: 1,
      current_discarded: 1,
      current_approved: 1,
      current_approved_without_card: 0,
      first_review_recall: { numerator: 1, denominator: 1 },
    },
    data_quality: {
      reviews_without_timestamp: 0,
      reviews_with_invalid_grade: 0,
      possible_duplicate_reviews: 0,
    },
  };

  return { decks, cards, templates, sources, errors, analytics };
}

/**
 * `break-ui` adversarial dataset:
 * - Schema max-length 120-char deck names, ZWJ emoji, Vietnamese diacritics, RTL Arabic, XSS strings
 * - 19-digit IDs exceeding Number.MAX_SAFE_INTEGER (9007199254740991)
 * - 0-card deck, 1-card deck (pluralization), and 10,000-card deck (count formatting & pagination)
 * - Unbreakable URLs, all statuses at once, data quality warnings
 */
export function buildWorstCaseDataset() {
  const today = new Date().toISOString().slice(0, 10);
  const decks = [
    {
      id: "9007199254740993123",
      name: "👩🏽‍💻 Aleksandra Wiśniewska-Kowalczyk · Benachrichtigungseinstellungen & Cloud Architecture Interviews (120 chars max!)",
      description: "Descripción extensa con diacriticos Đặng Thị Ngọc Hân, árabe نور الهدى عبد الرحمن, código literal <script>alert(1)</script> y URL sin espacios https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved.",
      _syntheticTotal: 10000,
      _syntheticDue: 1284,
    },
    {
      id: "9007199254740993124",
      name: "J",
      description: "",
      _syntheticTotal: 1,
      _syntheticDue: 1,
    },
    {
      id: "9007199254740993125",
      name: "🦊 Mazo vacío sin tarjetas (0 elementos) · Đặng Thị Ngọc Hân",
      description: "Prueba de estado vacío y barra de progreso en 0 % sin división entre cero.",
      _syntheticTotal: 0,
      _syntheticDue: 0,
    },
    {
      id: "9007199254740993126",
      name: "نور الهدى عبد الرحمن · <img src=x onerror=alert(1)> · **markdown**",
      description: "Prueba de escape estricto de HTML y texto bidireccional.",
      _syntheticTotal: 42,
      _syntheticDue: 0,
    },
  ];

  const cards = [
    {
      id: "9007199254740999001",
      deck_id: "9007199254740993123",
      front: "bartholomew.fitzgerald@northwind-industries-holdings.example.com preguntó cómo manejar ____ en Benachrichtigungseinstellungen sin romper <script>alert(1)</script> ni Đặng Thị Ngọc Hân.",
      back: "Usa overflow-wrap: anywhere, min-width: 0 en columnas flex/grid y escapa siempre como texto plano (nunca innerHTML).\nLínea 2 con ruta larga: https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved",
      kind: "cloze",
      source_label: "customer-feedback-from-enterprise-onboarding-very-long-label-v12",
      accepted_answers: [
        "overflow-wrap: anywhere",
        "min-width: 0 en contenedores flex/grid",
        "escapar texto con textContent",
        "<b>literal html tag</b>",
      ],
      explanation: "ID real de 19 dígitos: 9007199254740999001 (supera Number.MAX_SAFE_INTEGER = 9007199254740991).",
      error_id: "9007199254740998001",
      repetitions: 14,
      interval_days: 365,
      ease_factor: 2.78,
      due_date: today,
    },
    {
      id: "9007199254740999002",
      deck_id: "9007199254740993124",
      front: "Una sola tarjeta para comprobar singular: «1 tarjeta pendiente» (no «1 tarjetas»).",
      back: "Singular correcto mediante Intl.PluralRules.",
      kind: "vocabulary",
      source_label: null,
      accepted_answers: [],
      explanation: null,
      error_id: null,
      repetitions: 0,
      interval_days: 0,
      ease_factor: 2.5,
      due_date: today,
    },
  ];

  const templates = buildDemoDataset().templates;

  const sources = [
    {
      id: "9007199254740997001",
      label: "Q3 Board Deck — FINAL (revised) v12 [approved by legal] · Đặng Thị Ngọc Hân",
      url: "https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved&ref=bartholomew.fitzgerald",
      normalized_url: "https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved&ref=bartholomew.fitzgerald",
      excerpt: "Texto largo de muestra con <script>alert('xss')</script>, caracteres vietnamitas Đặng Thị Ngọc Hân y nombre alemán Benachrichtigungseinstellungen para verificar que nada desborda en 320 px.",
      status: "draft",
    },
    {
      id: "9007199254740997002",
      label: "a",
      url: "https://a.test",
      normalized_url: "https://a.test/",
      excerpt: null,
      status: "approved",
    },
    {
      id: "9007199254740997003",
      label: "Fuente descartada con etiqueta muy extensa para validar que las insignias no se partan en dos líneas",
      url: null,
      normalized_url: null,
      excerpt: "Sin URL asociada.",
      status: "discarded",
    },
  ];

  const errors = [
    {
      id: "9007199254740998001",
      attempted: "Prompt: bartholomew.fitzgerald@northwind-industries-holdings.example.com\nAnswer: I am agree that <script>alert(1)</script> depends of Benachrichtigungseinstellungen in Monday.",
      corrected: "I agree that the configuration depends on the notification settings on Monday.",
      rationale: "[Technical remediation] ID 9007199254740998001 — Verificación de texto largo, saltos de línea y caracteres especiales sin desbordamiento.",
      status: "draft",
      card_id: null,
    },
    {
      id: "9007199254740998002",
      attempted: "🦊",
      corrected: "Respuesta concisa aprobada",
      rationale: "[STAR remediation] Caso con emoji inicial y estado approved.",
      status: "approved",
      card_id: "9007199254740999001",
    },
    {
      id: "9007199254740998003",
      attempted: "Descartado con ID gigante",
      corrected: "N/A",
      rationale: "Estado discarded simultáneo en la misma lista.",
      status: "discarded",
      card_id: null,
    },
  ];

  const analytics = {
    semantics_version: 1,
    date_timezone: "America/Cancun",
    start: "2026-01-01",
    end: "2026-11-26",
    reviews: {
      recall: { numerator: 9876, denominator: 10000 },
      lapse: { numerator: 124, denominator: 9876 },
    },
    practice: {
      sessions: 1284,
      first_review_at: "2025-12-31T23:30:00Z",
      last_review_at: "2026-11-26T22:55:00Z",
      first_review_cancun_date: "2025-12-31",
      last_review_cancun_date: "2026-11-26",
      observed_span_seconds: 4622400,
      active_study_seconds: null,
      response_seconds: null,
    },
    error_correction: {
      current_drafts: 128,
      current_discarded: 42,
      current_approved: 1045,
      current_approved_without_card: 3,
      first_review_recall: { numerator: 812, denominator: 1042 },
    },
    data_quality: {
      reviews_without_timestamp: 2,
      reviews_with_invalid_grade: 1,
      possible_duplicate_reviews: 4,
    },
  };

  return { decks, cards, templates, sources, errors, analytics };
}

export function buildEmptyDataset() {
  return {
    decks: [],
    cards: [],
    templates: buildDemoDataset().templates,
    sources: [],
    errors: [],
    analytics: {
      semantics_version: 1,
      date_timezone: "America/Cancun",
      start: null,
      end: null,
      reviews: {
        recall: { numerator: 0, denominator: 0 },
        lapse: { numerator: 0, denominator: 0 },
      },
      practice: {
        sessions: 0,
        first_review_at: null,
        last_review_at: null,
        first_review_cancun_date: null,
        last_review_cancun_date: null,
        observed_span_seconds: null,
        active_study_seconds: null,
        response_seconds: null,
      },
      error_correction: {
        current_drafts: 0,
        current_discarded: 0,
        current_approved: 0,
        current_approved_without_card: 0,
        first_review_recall: { numerator: 0, denominator: 0 },
      },
      data_quality: {
        reviews_without_timestamp: 0,
        reviews_with_invalid_grade: 0,
        possible_duplicate_reviews: 0,
      },
    },
  };
}
