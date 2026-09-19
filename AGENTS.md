# AGENTS.md

# Project Coding Agent Instructions

This repository contains a market scanner, research platform, historical
analysis system, frontend, backend, workers, and supporting infrastructure.

The coding agent is allowed to work autonomously inside this repository,
subject to the rules in GUARDRAILS.md.

GUARDRAILS.md contains hard safety boundaries and takes precedence over this
file.

---

## 1. Primary Responsibility

Focus only on this project.

You may:

- inspect repository files
- create files
- edit files
- refactor code
- delete obsolete project code when clearly safe
- run project tests
- add/update tests
- run formatters and linters
- build frontend/backend
- run Docker Compose for this project
- create safe database migrations
- update project documentation
- inspect project logs
- diagnose project failures
- improve maintainability
- improve test coverage
- improve application security

Do not perform unrelated work on the host machine.

---

## 2. Repository Scope

Treat the repository root as the normal filesystem boundary.

Do not modify files outside the repository unless the user explicitly
authorizes the specific action.

Do not modify:

- operating-system configuration
- shell profiles
- SSH configuration
- global Git configuration
- firewall configuration
- router/network configuration
- Kubernetes clusters
- unrelated Docker resources
- unrelated repositories
- user documents
- home-directory configuration

Project-local Docker resources are allowed.

---

## 3. Existing Architecture

Before implementing a change:

1. inspect the relevant existing implementation
2. inspect existing tests
3. inspect relevant documentation
4. understand existing abstractions
5. reuse existing architecture where reasonable

Do not create parallel implementations of functionality that already exists.

Prefer extending existing abstractions over introducing unnecessary new ones.

---

## 4. Current Architectural Principles

Preserve these principles unless the user explicitly changes them.

### Market data

Market-data providers must remain behind provider-neutral abstractions.

Provider-specific SDK objects should not leak into strategy logic.

Current provider details must not become hard dependencies of the domain
model.

### Strategy

Scanner strategy must remain deterministic unless explicitly stated
otherwise.

Do not invent trading rules.

Do not silently change:

- EMA rules
- VWAP calculations
- FORMING conditions
- entry logic
- exit logic
- stop logic
- grading logic
- sector rules

Strategy behavior changes require explicit requirements.

### Research

Historical research must avoid look-ahead leakage.

At observation time T, features may contain only information that was
available at or before T.

Future candles may be used only for outcome evaluation.

Historical records should remain reproducible.

### Strategy versions

Never silently rewrite historical strategy behavior.

Material strategy changes should produce a new strategy version.

Historical observations must remain associated with the strategy version
that generated them.

---

## 5. Private vs Public Architecture

The system is expected to eventually support:

### Private experience

May contain:

- scanner
- watchlist upload
- discovery provenance
- detailed technical information
- Research
- Strategy Lab
- Rules
- historical observations
- outcomes
- strategy versions
- diagnostics
- administration

### Public experience

Should eventually contain only trader-facing information such as:

- scanner results
- symbol
- price
- percent change
- sector
- market context
- setup state
- alerts
- simplified stock details

Do not expose private information through public APIs.

Frontend hiding is NOT a security boundary.

Public DTOs must not contain private fields.

---

## 6. Sensitive Strategy Information

Treat the following as private implementation information:

- watchlist provenance
- discovery provenance
- internal rule thresholds
- strategy configuration
- strategy versions where unnecessary publicly
- research observations
- backtrace information
- experimental rules
- internal scoring
- provider/debug information

Do not expose these through normal/public frontend APIs.

---

## 7. Watchlist Terminology

The uploaded watchlist is one discovery source.

Use neutral terminology such as:

UPLOADED_WATCHLIST

Do not introduce user-facing branding around the origin of the uploaded
watchlist.

The application itself must remain source-agnostic.

---

## 8. Security Philosophy

Assume the browser is untrusted.

Strategy decisions belong on the backend.

Never move proprietary scanner logic into frontend JavaScript merely for
convenience.

Never expose secrets to the frontend.

Use:

- input validation
- bounded pagination
- safe ORM/database access
- sanitized errors
- rate limiting where applicable
- explicit CORS configuration
- appropriate security headers
- authentication/authorization boundaries

Do not implement custom cryptography.

Do not implement homemade authentication protocols when a mature solution is
appropriate.

---

## 9. Secrets

Never print, expose, commit, copy, or intentionally inspect secret values.

Examples:

- Alpaca API keys
- database passwords
- API tokens
- future OpenAI keys
- authentication secrets
- private keys

`.env` may exist but should be treated as sensitive.

Use `.env.example` with placeholders for documentation.

If configuration requires a secret, reference the environment variable name,
not its value.

---

## 10. Database Changes

Database migrations must be:

- additive where practical
- backward-safe where practical
- reviewable
- non-destructive by default

Do not:

- drop production tables
- truncate data
- delete historical research
- reset the database
- rewrite historical observations

unless the user explicitly authorizes the destructive operation.

Never solve a migration problem by deleting the database.

---

## 11. Historical Data

Historical scanner/research data is valuable.

Preserve:

- observations
- candle revisions
- outcomes
- discovery history
- sector history
- strategy versions
- rule history

Do not rewrite historical values simply to make new code easier.

If old data cannot support a new field accurately, use NULL/UNKNOWN rather
than inventing historical information.

---

## 12. Trading Safety

This project performs market research and scanner analysis.

Do not add:

- brokerage order placement
- automatic trade execution
- unattended buy/sell functionality

unless explicitly requested in a future task.

Research simulations must be clearly distinguished from actual trades.

Terms such as WIN/LOSS must not be assigned until deterministic simulated
entry, stop/invalidation, target/exit and resolution rules have been defined.

---

## 13. Testing

Every meaningful behavior change should include tests.

Before completing work, run relevant:

- unit tests
- integration tests
- frontend tests
- frontend build
- formatting/lint checks
- database migration verification

Do not remove failing tests merely to obtain a green build.

Fix the underlying problem or clearly report why the test is no longer valid.

---

## 14. Documentation

Documentation is part of implementation.

Definition of done:

CODE CHANGE + TESTS + DOCUMENTATION = COMPLETE CHANGE

Maintain as applicable:

- README.md
- docs/architecture.md
- docs/strategy.md
- docs/frontend.md
- docs/research.md
- docs/discovery.md
- docs/security.md

Do not document planned functionality as implemented.

Clearly distinguish:

IMPLEMENTED
EXPERIMENTAL
PROPOSED
BACKLOG
TBD

---

## 15. Dependency Discipline

Avoid unnecessary dependencies.

Before adding a dependency, determine whether the existing stack can solve
the problem cleanly.

Do not introduce infrastructure such as:

- Kafka
- Redis
- Celery
- Airflow
- service mesh
- Kubernetes

unless the requirement actually justifies it.

Prefer the simplest architecture that satisfies the requirement.

---

## 16. Code Quality

Prefer:

- small cohesive modules
- explicit types
- descriptive names
- clear boundaries
- dependency injection where useful
- provider-neutral domain models
- testable business logic

Avoid:

- giant utility modules
- hidden global state
- duplicated strategy calculations
- hard-coded secrets
- unexplained magic numbers
- provider-specific objects throughout the application

Trading thresholds must be configurable and documented.

---

## 17. When Requirements Are Ambiguous

Do not invent business/trading behavior.

If ambiguity affects:

- strategy behavior
- entry/exit logic
- historical correctness
- security
- destructive operations
- public/private exposure

stop and ask the user.

For ordinary implementation details, make the smallest reasonable assumption
and document it.

---

## 18. Completion Reports

After substantial work, report:

1. what changed
2. files changed
3. migrations
4. tests executed
5. test results
6. documentation updated
7. assumptions
8. limitations
9. security implications
10. anything requiring user review

Never claim something was tested if it was not actually tested.