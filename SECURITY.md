# SEAM Security Policy

SEAM is a local-first memory runtime for agents. Security reports should be handled privately and with enough detail for the project owner to reproduce and fix the issue.

## Supported versions

The `main` branch is the active development line. Security fixes target `main` first unless a separate maintained release branch is created.

## Private reporting

Please do not open a public issue for security-sensitive reports.

Use GitHub private vulnerability reporting if it is enabled for this repository. If private reporting is not available, contact the project owner privately through the contact channel listed in the repository profile or release notes.

## What to include

A useful report should include:

- affected command, module, API endpoint, installer, dashboard surface, or document path;
- steps to reproduce;
- expected behavior;
- actual behavior;
- impact assessment;
- environment details when relevant; and
- a minimal proof of concept that does not expose private data.

## Handling sensitive material

Do not include secrets, customer data, private transcripts, credential material, private service URLs, or unrelated personal information in a report. Redact sensitive values before sharing logs or examples.

## Scope

Security reports may cover runtime behavior, installers, API authentication, benchmark bundle verification, provenance handling, private data exposure, dependency risk, or unsafe agent workflows.

Commercial use, hosted service use, SaaS use, embedded use, redistribution, and customer deployment remain governed by `LICENSE`, `NOTICE`, and `COMMERCIAL_LICENSE.md`.

Exact historical source-available releases retain the security-research and
self-host rights granted by the license shipped with each artifact. This
private repository makes no public security-research or self-host grant;
written authorization or a separately licensed SDK/Node artifact is required.
