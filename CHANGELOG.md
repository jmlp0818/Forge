# Changelog

## 0.15.0 — 2026-10-24 — preview

- Correct application identity to `io.github.jmlp0818.Forge`; this is a separate Flatpak from 0.14.0, with migration instructions.
- Reject cleanup paths with symlinked parent directories.
- Check file change time as well as inode, size, and modification time before deleting previewed files.
- Persist small local operation markers for native, Flatpak, and cleanup changes. An interrupted or failed operation prompts review after restart. Operations are never replayed or rolled back automatically.
- Detect PackageKit service replacement during a transaction and retain an error instead of waiting indefinitely for completion.
- Treat Flatpak output read failures as errors, rather than accepting incomplete output.
- Remove bundled third-party PNG icons with unverified redistribution notices; use desktop theme/fallback icons.
- Add complete source releases, local and archive-pinned GitHub build manifests, build records, checksums, screenshots, metadata links, and maintenance documentation.

## 0.14.0 — 2026-10-24 — preview

Initial GitHub installer release with app discovery, native and Flatpak update queues, setup checks, tray/background preferences and storage cleanup previews. The old application ID was `io.github.forge.PackageManager`.
