# Contributing

Start with an issue describing the problem, distribution, desktop, version, scope and reproducible steps. Avoid private logs and identifiers. Keep fixes focused, document limitations, and disclose AI-generated contributions.

Run `python3 -m unittest discover -s tests -v` before proposing code changes. Use disposable homes for cleanup tests and separate Flatpak installations for package tests. Do not test deletion or privileged package changes on a person's normal data/system as an automated check.

Changes to native package actions, host-command access, cleanup, authentication or recovery need targeted failure-path tests. Do not bypass signature checks, administrator authorization or source confirmation. Check offline/error behavior and preserve unfinished selections.

Maintainers must review release artifacts, source/checksum consistency and the validation matrix in `docs/VALIDATION.md`. A green automated check is not a substitute for desktop and package-manager testing.
