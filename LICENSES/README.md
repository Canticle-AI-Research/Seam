# SEAM license-text registry

This directory separates current package notices from historical evidence.

| Path | Role | Grants rights in current private SEAM? |
| --- | --- | --- |
| `Apache-2.0.txt` | required text for exact unchanged Legacy Apache Materials | only for the exact legacy material carrying that license |
| `HISTORICAL/BUSL-1.1.txt` | last BUSL parameters shipped with historical source-available releases | no |

The root `LICENSE` is the current proprietary repository license. Historical
license texts are retained because later policy cannot revoke rights already
granted for exact published artifacts. Their presence does not relicense later
private versions.

PolyForm Shield text is intentionally absent here. Current Shield grants belong
in the separate source-distributed SEAM SDK and SEAM Node repositories and
their artifacts, not in the canonical private runtime package.
