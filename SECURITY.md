# Security

Forge is preview software that manages host packages and permanently deletes selected cleanup files. It uses broad host-command access and has no rollback facility. Do not assume the Flatpak isolates it from your host.

Only the newest preview receives fixes in this project; no response-time or long-term-support guarantee is offered. Maintainers should triage reports, pause affected features/distribution if needed, and publish a fix with clear release notes.

For a suspected vulnerability, open an issue containing a minimal, non-sensitive description and request a private reporting route before sharing exploit details. No private contact address is currently established. Never post credentials, personal data, or a working exploit against another person's computer.

Do not run Forge as root. Keep the distribution, Flatpak and runtime updated. Obtain releases only from the project's GitHub repository and compare SHA-256 checksums. Current bundles are unsigned; checksums on the same release page do not independently prove publisher identity.
