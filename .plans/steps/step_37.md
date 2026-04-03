# Step 37: Public Documentation

## Goal

Maintain first-release public documentation as a separate static site built with Starlight.

## Decisions

- Generator: `@astrojs/starlight`
- Public documentation lives inside the dedicated `docs/` app
- The first iteration is limited to three sections:
  - `Introduction`
  - `How to Run`
  - `Scenario`
- Use a pinned dependency set compatible with the official Starlight example tree
- Disable the built-in Starlight 404 route and use a custom `src/pages/404.astro`

## Implementation

[x] Created the Starlight app in `docs/` (`package.json`, `astro.config.mjs`, content config, public assets).
[x] Added pages:
  - `src/content/docs/index.mdx`
  - `how-to-run.md`
  - `scenario.md`
[x] Documented install flow through PyPI and startup through `vikhry infra up`.
[x] Documented scenario structure, lifecycle hooks, step fields, and the resource model.
[x] Added local docs build and dev commands to `README.md`.
[x] Added the publishing flow for GitHub Pages.

## Progress

- [x] Starlight selected and integrated
- [x] Initial `Introduction`, `How to Run`, and `Scenario` sections completed
- [x] `npm run build` and `npm run check` passing
- [ ] GitHub Pages publishing is not fully wired yet

## Risks and Checks

- Docs content should stay lean and avoid drifting back into `README.md` duplication.
- `How to Run` must remain synchronized with real CLI flags.
- Starlight dependency updates must preserve a working lock tree; floating patch versions already broke `astro build` before.
