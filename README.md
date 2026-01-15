# 🎙️ Episodic

> **AI-powered podcast generation that sounds human, works like software.**

_Totally not a versificator. Honest._

______________________________________________________________________

## What is Episodic?

Episodic is an automated podcast generation platform that transforms your
content into professional, scripted audio shows. Using AI orchestration with
human oversight, it takes heterogeneous source documents and produces
broadcast-quality podcasts with proper tone, compliance checks, and audio
mastering.

Think of it as your podcast production team, but with:

- **Intelligent content generation** using LLMs with multi-layer quality
  assurance
- **Human-in-the-loop workflows** for editorial approval and brand compliance
- **Professional audio synthesis** with TTS, background music, and loudness
  normalization
- **Hexagonal architecture** for clean boundaries and testable components
- **Cloud-native infrastructure** built on Kubernetes with GitOps deployment

Unlike certain dystopian content machines from Orwell's imagination, Episodic
emphasizes auditability, compliance, brand guidelines, and human oversight at
every stage. It's a tool for creators, not a replacement.

## 🚧 Work in Progress

This project is in **active early development**. We're currently building the
platform foundations (Phase 1 of 6).

📋 See [`docs/roadmap.md`](docs/roadmap.md) for detailed development status and
planned features.

## Features

### 🔄 Content Pipeline

- Multi-source document ingestion with conflict resolution
- Canonical TEI (Text Encoding Initiative) content representation using
  [tei-rapporteur](https://github.com/leynos/tei-rapporteur), our TEI P5
  serialization library for Rust and Python
- Automated provenance tracking and audit trails
- Series profiles and episode templates

### 🤖 AI Orchestration

- LLM-based script generation with retry and guardrails
- Multi-layer quality assurance (factuality, tone, style)
- Brand guideline compliance checking
- Structured output planning with model tiering for cost control
- LangGraph suspend-and-resume workflows

### 🎵 Audio Production

- Text-to-speech with configurable voice personas
- Background music and sound effect integration
- Professional mixing with ducking and transitions
- Loudness normalization to broadcast standards (-16 LUFS)
- Chapter markers and metadata embedding

### 📊 Operations & Compliance

- Cost accounting with token usage metering
- Budget enforcement per user/organization
- Comprehensive observability (Prometheus, Loki, Tempo)
- GitOps-driven deployments with FluxCD
- Editorial approval workflows with SLA tracking

## Technology Stack

- **Language:** Python 3.13+ (with optional Rust extensions)
- **Web Framework:** [Falcon](https://falconframework.org/) 4.2.x on
  [Granian](https://github.com/emmett-framework/granian) (Rust-based ASGI
  server)
- **Task Queue:** Celery with RabbitMQ
- **Orchestration:** [LangGraph](https://langchain-ai.github.io/langgraph/) for
  agentic workflows
- **Database:** PostgreSQL ([CloudNativePG](https://cloudnative-pg.io/))
- **Cache:** [Valkey](https://valkey.io/) (Redis-compatible in-memory data
  store)
- **Infrastructure:** Kubernetes (DigitalOcean DOKS), OpenTofu/Terraform
- **Deployment:** FluxCD GitOps
- **Testing:** pytest with BDD (pytest-bdd)

### Architecture

Episodic is built using **hexagonal architecture** (ports and adapters) to
maintain clean boundaries between domain logic and infrastructure concerns.
This ensures testability, flexibility, and long-term maintainability.

## Getting Started

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (fast Python package and project manager)
- Make
- Docker (for local development)

### Development Setup

```bash
# Install dependencies
uv sync

# Run tests
make test

# Run linters and type checks
make lint
make typecheck
```

### Usage

📖 See [`docs/users-guide.md`](docs/users-guide.md) for the knick-knacks.

> User guide coming soon as features are implemented!

## Documentation

- [**Roadmap**](docs/roadmap.md) — Development phases and current status
- [**System Design**](docs/episodic-podcast-generation-system-design.md) —
  Architecture and component overview
- [**Infrastructure Design**](docs/infrastructure-design.md) — Kubernetes,
  GitOps, and observability
- [**Users Guide**](docs/users-guide.md) — Usage instructions (coming soon)

## Contributing

This project follows strict code quality standards:

- **Linting:** Ruff with comprehensive rule sets
- **Type Checking:** Pyright in strict mode
- **Testing:** pytest with BDD scenarios
- **Complexity:** Cyclomatic complexity limits enforced
- **Architecture:** Hexagonal boundary enforcement via lint rules

See [`AGENTS.md`](AGENTS.md) for contributor guidelines and commit gating
requirements.

## Licence

Licensed under the [ISC Licence](LICENSE).

## Credits

Developed by **df12 Productions** 🌐 [https://df12.studio](https://df12.studio)

______________________________________________________________________

_Remember: With great automation comes great responsibility. Use this power
wisely, and keep a human in the loop._ 🤖✨
