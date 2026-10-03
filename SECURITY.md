# SEAM Security Policy

SEAM is a local-first memory runtime for agents. Security reports should be handled privately and with enough detail for the project owner to reproduce and fix the issue.

## Supported versions

The `main` branch is the active development line. Security fixes target `main` first unless a separate maintained release branch is created.

## Private reporting

Please do not open a public issue for security-sensitive reports.

Open a private security advisory at
<https://github.com/Canticle-AI-Research/Seam/security/advisories/new>. If
private vulnerability reporting is disabled for this repository, contact the
project owner privately through a channel listed on the repository profile.

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

Self-hosting the SEAM Distributed Runtime is free under the Business Source License 1.1 (`LICENSES/BUSL-1.1.txt`), including for internal commercial production use at any scale. Security research on it, and publication of the results, is permitted.
