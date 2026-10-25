# Validation — 0.15.0 preview, 2026-10-24

These results describe bounded checks, not certification or a complete security audit. Development history in DEVELOPMENT-HISTORY.md describes earlier versions; it is not evidence that all those checks were rerun for 0.15.0.

| Check | Environment | Result / limit |
| --- | --- | --- |
| Unit and regression suite | Fedora host, Python 3.14 | 90 tests passed |
| Unit and regression suite | Clean Ubuntu 24.04 container, Python 3.12, Xvfb | 90 tests run; passed with 1 skip: host PackageKit introspection unavailable |
| Unit and regression suite | Clean Arch container, current packages, Xvfb | 90 tests run; 1 error and 1 skip: host PackageKit introspection unavailable. Tray PNG decoding failed because Glycin's nested bubblewrap loader could not start inside the container. This does not establish Arch desktop compatibility. |
| Cleanup protection | Temporary test homes only | Changed files, same-size changes with restored mtime, newly added files, symlink replacement, symlinked root ancestors, traversal and Trash links covered |
| Failure handling | Mock PackageKit signals and real subprocess transport with simulated errors | Service replacement, cancelled-auth text, network-error text, process termination, retained interruption markers, success-marker removal covered; actual polkit cancellation and network outages during a real package transaction remain untested |
| Flatpak lifecycle | Real temporary local repo and separate FLATPAK_USER_DIR | Fixture install, pending update, scoped update, recheck and uninstall passed; no real user app was changed |
| Packaged Forge | Separate temporary Flatpak installation, system GNOME Platform 51 | Installed bundle identified as 0.15.0 / io.github.jmlp0818.Forge; GUI launched/exited in demo mode |
| Desktop metadata | appstreamcli and desktop-file-validate | Validation passed. One pedantic hint about uppercase in the reverse-DNS app ID; not a validation error |
| Screenshots | Current source demo mode with temporary config/cache/state | Discover and Settings captured; no package changes |
| Hosted automation | GitHub Actions workflow added | No successful hosted run yet; the first job did not start due to an account-level restriction. Local results below are the evidence for this preview. |
| Source packaging | Deterministic ordered tar/gzip, fixed timestamps/ownership | Repeated source archives matched; clean extraction passed 90 tests and rebuilt successfully. Source roundtrip bytes matched; installer bytes differed between same-host builds, so bit-for-bit bundle reproducibility is not established |
| Secret/path review | Release source tree | Checked common credential patterns and personal absolute paths; no matches in released source |

Commands:

```sh
python3 -m unittest discover -s tests -v
python3 tests/integration_flatpak.py
appstreamcli validate --no-net data/io.github.jmlp0818.Forge.metainfo.xml
desktop-file-validate data/io.github.jmlp0818.Forge.desktop
python3 packaging.py build ../forge-release
```

Containers exercise Python/toolkit logic with virtual displays. They are not complete GNOME/KDE desktops and do not test native package changes. The local fixture relaxes signature verification only for its own temporary test repository; production sources and host trust policies are unchanged.

## Required before a stable claim

- Fresh Fedora, Ubuntu and Arch desktop/VM installation, then native install/update/remove on disposable packages with a real PackageKit backend.
- Real administrator-prompt cancellation, source failure, network loss and interrupted operation recovery in those VMs.
- GNOME and KDE login/startup, tray absence/loss, foreground/background permission behavior and accessibility checks.
- Review destructive cleanup behavior with disposable data; independently review deletion and host-command code.
- Test desktop-specific runtime installation and old-ID migration with typical graphical software installers.
- Establish a signed distribution/update channel if automatic Forge updates are promised.
- Human review of provenance, licensing and store eligibility. No Flathub acceptance is implied.

Rollback, power-loss recovery, queue persistence across process death and automatic Forge updates are not implemented. The interruption notice prompts a fresh state check; it does not restore or replay transactions. Setup/prerequisite actions currently do not have their own interruption marker.
