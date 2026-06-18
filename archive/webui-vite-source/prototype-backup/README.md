# SEAM WebUI Prototype

This folder holds the active IDE-like browser dashboard prototype.

Current role:

- Visual target for the future REST API GUI.
- Active prototype, not packaged runtime behavior.
- The stable terminal dashboard remains `seam dashboard` / `seam-dash`.

Promotion path:

1. Split `seam-dashboard-prototype.html` into a maintainable web app shell.
2. Replace CDN/Babel prototype loading with local build tooling.
3. Wire panes to real SEAM REST endpoints.
4. Add browser smoke tests before moving code into packaged runtime paths.

Secrets rule: keep API keys and bearer tokens in local environment/config only.
