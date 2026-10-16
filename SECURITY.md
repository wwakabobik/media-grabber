# Security Policy

## Supported versions

This is a small personal desktop tool with a single rolling release line — only the latest
version on `master` is supported. There's no LTS branch; update to the latest release if you
hit a security issue.

## Reporting a vulnerability

Please **don't** open a public issue for a security problem. Instead, use GitHub's private
reporting:

1. Go to the [Security tab](https://github.com/wwakabobik/media-grabber/security) of this repo.
2. Click **"Report a vulnerability"** to open a private advisory.

If that's not available for some reason, open an issue asking for a contact channel without
including exploit details, and it'll be followed up privately.

## Scope notes

A few things that are *known* and not considered vulnerabilities to report:

- The Yandex Music OAuth token is stored in plain text in `~/.config/media-grabber/state.json`
  (same as most desktop apps that need a personal token — there's no OS keychain integration
  here, by design, to keep the app dependency-free). Don't share that file.
- This app downloads and executes `ffmpeg` postprocessing over files it itself fetches from
  the URL you give it — it does not execute arbitrary third-party code, but a malicious
  video/audio file processed by `ffmpeg` is the same trust boundary any such tool has.
- Dependabot flags several `starlette`/`anyio` CVEs (DoS, SSRF, request-smuggling-style issues
  in their HTTP server code). Both come in transitively via `spotdl` → `fastapi==0.103.x`,
  which hard-pins old `starlette`/`anyio` ranges upstream — not something this repo can bump on
  its own without either waiting for spotdl to move off that `fastapi` pin, or forcing a
  starlette major-version jump that's very likely incompatible with it. In practice this app
  never starts spotdl's bundled web server (only its Spotify-search/download client functions
  are used), so the vulnerable HTTP-request-handling code paths are never reachable at runtime
  — tracked, not silently ignored, but not worth a risky forced override for a server this app
  never runs.
- Dependency vulnerabilities are tracked via GitHub's Dependabot alerts and version-update PRs
  (`.github/dependabot.yml`), not manually.
