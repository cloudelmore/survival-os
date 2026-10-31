# Contributing

1. Follow [docs/dev/windows-wsl2-setup.md](docs/dev/windows-wsl2-setup.md), then run `make test`.
2. Keep changes focused, and add tests for new behavior.
3. Write descriptive commit messages.

Rules that always apply:

- The running system must work with no network: no CDNs, external fonts or hosted services.
- Never commit ZIMs, video, map files, model weights, private data or secrets.
- Do not claim something works until it has been tested. Record results in `docs/STATUS.md`.
- Catalog entries may only mark a field `verified` after checking it live at the source.
- Bundled assets need a license that allows redistribution, and must be original or properly
  attributed.
