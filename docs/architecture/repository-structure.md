# Repository Structure

Newbro uses a role-based repository layout with Python runtime code under `src/`
and first-party clients, executor app wrappers, and prototypes kept outside the
runtime package.

Canonical repository structure:

```text
.
├─ ARCHITECTURE.md
├─ README.md
├─ LICENSE
├─ CONTRIBUTING.md
├─ pyproject.toml
├─ install.sh
├─ clients/
│  ├─ web/
│  └─ cardputer/
├─ executor-apps/
│  └─ macos/
├─ prototypes/
│  └─ design/
├─ docs/
├─ examples/
├─ schemas/
├─ tests/
├─ evals/
├─ scripts/
└─ src/
   └─ newbro/
      ├─ __init__.py
      ├─ protocol/
      ├─ blackboard/
      ├─ communication/
      ├─ execution/
      ├─ executors/
      ├─ notification/
      ├─ runtime/
      ├─ api/
      ├─ connectors/
      ├─ cli/
      ├─ ui/
      └─ infrastructure/
```

Recommended package structure inside `src/newbro/`:

```text
src/newbro/
├─ protocol/
├─ blackboard/
├─ communication/
├─ execution/
├─ executors/
│  ├─ core/
│  ├─ adapters/
│  └─ node/
├─ interaction/
├─ notification/
├─ runtime/
├─ service/
├─ api/
├─ connectors/
│  ├─ base/
│  ├─ host/
│  └─ voice/
├─ cli/
├─ observability/
└─ infrastructure/
```

Organizing rule:

- by domain
- not by framework
- not by generic backend layer names

The most stable public boundaries should be:

- `newbro.protocol`
- `newbro.blackboard.interfaces`
- `newbro.executors.core`

This keeps the project easier to understand and extend in open source.

Additional repository-level guidance:

- `ARCHITECTURE.md`
  - single-entry open-source architecture overview
- `clients/`
  - first-party user-facing clients such as the React/Vite web app and Cardputer
    firmware
  - keep reusable backend, connector, and executor runtime logic out of this
    directory
- `executor-apps/`
  - platform-specific wrappers that supervise executor-node workflows
  - keep executor contracts, adapters, and `newbro executor ...` logic in
    `src/newbro`
- `prototypes/`
  - design explorations and non-production prototypes
- `tests/`
  - deterministic correctness
- `evals/`
  - behavior-quality validation
- `scripts/`
  - repository maintenance and dev helpers
- `examples/`
  - minimal runnable demos and integration examples

Migration rule:

- current `runtime/` remains a temporary prototype structure during migration
- target package identity is `newbro`
- avoid introducing a second public package name
