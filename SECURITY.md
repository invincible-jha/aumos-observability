# Security Policy

## Reporting a Vulnerability

The AumOS platform team takes security vulnerabilities seriously. We appreciate your
efforts to responsibly disclose your findings.

**Please do NOT report security vulnerabilities through public GitHub issues.**

### How to Report

Email your findings to: **security@aumos.io**

Include in your report:
- A description of the vulnerability and its potential impact
- Steps to reproduce the issue
- Any proof-of-concept code (if applicable)
- Your recommended fix (if you have one)

You will receive an acknowledgment within **48 hours** and a detailed response
within **5 business days**.

## Scope

The following are in scope for security reports:

- Authentication and authorization bypass
- Tenant isolation violations (RLS bypass, cross-tenant metrics/logs/traces access)
- SQL injection or other injection attacks
- PromQL injection via the ad-hoc metrics query endpoint
- Remote code execution
- Sensitive data exposure (credentials, PII, tenant data in logs/traces)
- Privilege escalation
- API security issues (broken object-level authorization, rate limiting bypass)
- Grafana API key exposure
- Langfuse credential exposure in trace metadata

The following are out of scope:

- Denial of service attacks
- Social engineering of AumOS staff
- Physical security issues
- Vulnerabilities in third-party services we do not control (Prometheus, Grafana, Loki)
- Issues in repositories not owned by AumOS Enterprise

## Response Timeline

| Stage | Timeline |
|-------|----------|
| Acknowledgment | Within 48 hours |
| Initial assessment | Within 5 business days |
| Status update | Every 7 days during investigation |
| Fix deployment (critical) | Within 7 days of confirmation |
| Fix deployment (high) | Within 30 days of confirmation |
| Fix deployment (medium/low) | Next scheduled release |

## Disclosure Policy

- We follow a **90-day coordinated disclosure** policy
- We will notify you when the fix is deployed
- We will credit you in our release notes (unless you prefer anonymity)
- We ask that you do not publicly disclose the vulnerability until we have released a fix

## Observability-Specific Security Considerations

### PromQL Injection

The ad-hoc metrics query endpoint (`POST /api/v1/metrics/query`) accepts raw PromQL
queries. PromQL is a read-only query language with no write operations, so injection
risk is limited to information disclosure. Tenant-scoped label enforcement is applied
where possible.

### Trace and Log Data Sensitivity

Langfuse traces and Loki logs may contain sensitive data (user inputs, model outputs).
Contributors must:
- Never log credentials, API keys, or PII
- Redact sensitive fields before sending to Langfuse/Loki
- Apply tenant-scoped label filtering on all log queries

### Grafana API Key Security

The Grafana API key (`AUMOS_OBSERVABILITY_GRAFANA_API_KEY`) grants dashboard admin
access. Treat this as a high-privilege credential:
- Rotate quarterly
- Use service accounts with minimal required scopes
- Never embed in Docker images or commit to version control

## Security Best Practices for Contributors

1. Never commit secrets, API keys, or credentials (even test credentials)
2. Use parameterized queries — never string concatenation in SQL
3. Validate all inputs at system boundaries using Pydantic
4. Never log sensitive data (tokens, passwords, PII, LLM inputs/outputs)
5. Check dependency licenses and security advisories before adding packages
6. Report any security issues you discover, even if you are not sure of the impact
