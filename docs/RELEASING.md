# Release procedure

1. Triage outstanding bugs, especially package changes, cleanup and authentication. Keep releases marked preview while full desktop/package-manager validation is incomplete.
2. Update VERSION in `forge.py` and `packaging.py`, AppStream release/date and the changelog. Keep the application ID stable after 0.15.0.
3. Run the unit suite, metadata validation and disposable integration tests. Record the commands, environment, results and remaining gaps in VALIDATION.md. Review screenshots for private information.
4. Commit the complete source, tests, documentation and assets. Tag that exact source for the release. Never reuse a version for different bytes.
5. Install GNOME Platform 51 from its official source if needed. `python3 packaging.py build ../forge-release` records its installed commit. The helper uses the runtime as the pure-Python build environment and requires no compiler. The separate flatpak-builder manifest uses GNOME SDK 51.
6. Verify `sha256sum -c SHA256SUMS` in the artifact directory. Extract the source archive in a fresh folder and rerun the tests/build. Test installation in an isolated Flatpak installation, using a temporary FLATPAK_USER_DIR. Never replace the normal user's application during automated release checks.
7. Publish a GitHub **pre-release** with the installer, source archive, SHA256SUMS, BUILD-INFO.json and Forge-GitHub-build.json. Attach the release tag to the source commit. Explain permissions, the unsigned bundle, identity migration and known limits. Check download links after publication.
8. Review incoming issues after release, keep the runtime current, and ship fixes as new versions. Pause a release with serious package/deletion faults; do not silently overwrite it.

## Update channel

GitHub bundles are manually downloaded and installed. They do not give Forge a trusted self-update source. Do not poll GitHub and silently install arbitrary bundles. A future automatic update channel needs a maintained Flatpak repository, managed signing keys, signed metadata, HTTPS hosting, a clear rotation/revocation procedure and client installation tests. Never publish private signing keys. Store distribution is a separate decision.

## Reproducibility limits

Source tarballs use ordered files, fixed timestamps, fixed ownership and deterministic gzip headers. The release manifest pins the source archive's checksum. BUILD-INFO records the runtime commit. Builds against different runtime commits need not match; byte-identical installers on different hosts have not been proven. The supplied build script does not pin or modify your globally installed runtime automatically.
