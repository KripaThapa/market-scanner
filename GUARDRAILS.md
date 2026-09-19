# GUARDRAILS.md

# Hard Safety Boundaries for Coding Agents

These rules override all other repository agent instructions.

The coding agent has broad autonomy INSIDE this repository.

It does NOT have broad autonomy over the machine, network, credentials,
production infrastructure, or user data.

---

## ALLOWED WITHOUT ADDITIONAL APPROVAL

Inside this repository:

- read project source code
- create/edit/refactor project code
- add/delete project files when safe
- run tests
- run linters/formatters
- build frontend/backend
- create safe database migrations
- run project-local Docker Compose
- inspect project-local logs
- update documentation
- improve tests
- improve application security
- modify project configuration that does not expose secrets or external
  infrastructure

---

## NEVER ACCESS OR MODIFY

Unless the user explicitly authorizes a specific action:

- files outside the repository
- SSH keys
- ~/.ssh
- browser credentials/cookies
- password stores/keychains
- cloud credentials
- unrelated environment variables
- unrelated repositories
- personal files
- operating-system configuration
- router configuration
- firewall configuration
- DNS configuration
- external servers
- Raspberry Pi host configuration
- Kubernetes clusters
- unrelated Docker containers/volumes/networks

---

## SECRETS

Never:

- print secrets
- log secrets
- commit secrets
- expose secrets through APIs
- expose secrets to frontend code
- place secrets in documentation
- copy secrets to another location

Treat `.env` as sensitive.

It is acceptable to identify that a variable exists or is missing.

Do not reveal its value.

---

## NETWORK / INTERNET

Do not:

- open public ports
- configure router port forwarding
- change firewall rules
- expose the development machine
- expose Raspberry Pis
- create public tunnels
- change DNS
- publish services
- deploy publicly

without explicit user authorization.

Do not download or execute arbitrary scripts from the Internet.

Do not use:

curl <url> | sh

or equivalent remote-code execution patterns.

---

## DESTRUCTIVE COMMANDS

Never run broad destructive commands such as:

rm -rf /
rm -rf ~
rm -rf ..
docker system prune -a
docker volume prune
DROP DATABASE
DROP SCHEMA
TRUNCATE
git clean -fdx
git reset --hard

unless the exact destructive action is explicitly requested and its impact
has been confirmed.

Prefer reversible operations.

---

## DATABASE

Do not destroy historical data.

Never solve schema/migration problems by resetting PostgreSQL.

Do not delete:

- historical observations
- candle history
- outcomes
- discovery history
- sector history
- strategy versions
- rules

without explicit authorization.

---

## GIT

Do not:

- force push
- rewrite shared history
- delete remote branches
- change remote URLs
- modify global Git configuration
- expose credentials

without explicit authorization.

Normal local commits/branches may be used if requested by the task.

---

## PUBLIC EXPOSURE

Assume frontend users are untrusted.

Never expose through public APIs:

- secrets
- uploaded-watchlist provenance
- private discovery provenance
- internal strategy thresholds
- research internals
- debug information
- database details
- filesystem paths

Frontend hiding does not count as protection.

Enforce privacy server-side.

---

## TRADING

Do not place trades.

Do not connect strategy signals to brokerage order execution.

Do not implement unattended order execution unless the user explicitly
authorizes such functionality in a future task.

Historical/paper simulations must remain clearly labeled as simulations.

---

## STRATEGY

Do not invent trading rules.

Do not silently modify existing strategy behavior.

Do not optimize thresholds merely to improve historical results.

Do not use future candles as input features for historical decisions.

Future data may only be used to evaluate outcomes.

---

## STOP AND ASK

Stop before an action involving:

- production deployment
- public Internet exposure
- credentials
- authentication secrets
- destructive database operations
- deletion of historical data
- firewall/network changes
- external infrastructure
- irreversible Git operations
- real brokerage/order execution
- material strategy behavior not defined by requirements

When uncertain, preserve data and choose the reversible path.