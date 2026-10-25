# Historical development notes from Forge 0.14.0

These notes were imported from the previous local development session. Commands were mechanically updated to the 0.15.0 application ID. References to the development workstation and earlier test results are historical; consult VALIDATION.md for the current release's checks and limitations.

A native GTK 4/libadwaita software browser and system-package updater for people moving from Windows to Linux. The primary download is `Forge.flatpak` (x86_64). It uses GNOME Platform 51 and needs a working host PackageKit backend for native package operations.

## Install and use

Open `Forge.flatpak` with your graphical software installer, install or update it, then launch Forge from the app menu. Flatpak must already be available; the installer may download the GNOME runtime. No Python setup is needed for the prebuilt bundle.

1. Browse Discover, search a task such as `edit photos`, or open **New to Linux**.
2. Open an app overview and choose **Find install options**.
3. Add a package to **Downloads**, then choose **Review changes**.
4. Read the complete plan before approving it. The system handles administrator authentication when needed.

Forge runs as your normal user and refuses to start as root. It does not invoke sudo, save passwords, or run a privileged shell. Flatpak app management uses the host-command permission described below.

## Update, search, panel, and setup fixes in 0.14.0

- **Add all updates to Downloads** gathers both native packages and both Flatpak installations. The Downloads count changes in the sidebar and footer, and the queue stays accessible during work. Native and Flatpak changes retain their separate confirmation steps.
- Flatpak write commands now allow the desktop authentication prompt. Native PackageKit calls set the interactive hint before starting, supporting both the legacy array and new dictionary forms. Background checks do not request interactive authentication.
- A successful update command is followed by a fresh update query. Completed selections leave Downloads; still-available or unverified selections remain. Native update selections adopt newer pending versions instead of retaining stale package IDs. Partial Flatpak batches refresh the queue before reporting the remaining issue.
- Discover searches the full enabled native package catalog automatically alongside curated suggestions; users no longer need an extra Search repositories button.
- First launch checks the host PackageKit service/backend, Python, and Flatpak. Missing supported prerequisites have an installation action through fixed distribution commands and normal administrator authorization. GNOME panel support is checked separately and can be installed through the official GNOME extension service. **Settings → Check setup** repeats the check. Desktop runtimes are still installed as Flatpak dependencies. Host setup is checked after launch because Flatpak cannot declare arbitrary native packages as runtime dependencies.
- On this GNOME machine AppIndicator support 66 was installed and enabled, its host reports active, and Forge is registered with it. No other extensions or login preferences were changed.

## Installer repair in 0.13.1

The bundle now includes its generated AppStream catalog and cached installer icon. Earlier manual exports omitted this catalog: Flatpak could deploy the app, but GNOME Software could show a source lookup error afterward and could not identify the installed name/version. A clean isolated install and an update of the current system installation both completed successfully; Flatpak and GNOME Software now identify Forge 0.13.1. The manifest runs `prepare_appstream.py` during builds to keep this metadata present. The downloaded filename `Forge-0.13.1.flatpak` also distinguishes this repair from previously opened files.

## What is included

- A storefront inspired by the feel of modern app stores, with 36 app ideas across 10 collections.
- Home-screen app update counts and a **Review app updates** action that checks both Flatpak installations and adds their app/runtime updates to Downloads in one step. It still requires review before installation.
- Publisher screenshots, current catalog icons, and catalog version labels for featured apps, read from configured Flathub AppStream metadata. Artwork is cached for offline use and checked daily while opening Discover. **Refresh artwork** also refreshes configured Flathub metadata without installing apps. Screenshot info gives the source URL and caption; artwork retains publisher terms. Missing artwork falls back to bundled icons.
- Local keyword/synonym search for tasks and familiar alternatives, plus host repository search.
- A New to Linux guide covering Office, Photoshop/drawing, media, plain-text editing, email, installation, software sources, and administrator prompts. Alternatives are suggestions, not promises of feature/file compatibility or migration.
- Thirty bundled app icons in browsing, the queue, transaction review, and active download/install status. Other packages use theme icons or a utility fallback. Artwork provenance is in `data/app-icons/ICONS.md` and `sources.json`.
- Light/dark/system themes, five accent colors, compact mode, and optional technical package details under **Settings**. Preferences are saved per user. Reset appearance preserves notification/background preferences.
- Library, system updates, actual configured source controls, and distro-specific source suggestions.
- Host distro/version detection from host os-release even inside Flatpak. An initial Arch alias map handles LibreOffice's suite package and Luanti. Suggestions do not automatically add sources or change release versions.
- Ctrl+F for search and Alt+Left for Discover.

## Startup, background, and update timing

Under Settings you can enable Launch Forge when I sign in, Start minimized at login, and Check updates when Forge starts. Login startup is off by default and uses the desktop Background portal inside Flatpak. The desktop may ask for permission; denial does not mark the option as enabled. Source/native runs use an app-owned XDG autostart file. Startup is per user after login, not a system boot service.

Periodic checks can be off or run every 15 minutes, 30 minutes, one hour, four hours, or 24 hours while Forge is running. Startup checking is a separate option. Closing can quit, minimize to the dock/taskbar, or hide in the tray. Tray hiding falls back to minimization when there is no verified visible tray host. The header says Tray or Dock to match what is available. Selecting tray close behavior also routes the window minimize action to the tray where supported. If tray support disappears while hidden, the window returns to the dock. **Settings → Desktop tray status** provides diagnostics, Retry, and a GNOME setup shortcut. GNOME needs a compatible AppIndicator extension enabled; Forge can request compatible extension installation through GNOME’s extension service; GNOME may ask for confirmation. Explicit Quit Forge exits, unless a package-changing operation is active. No real login preference was changed during development/testing.

Checks cover native system packages plus Flatpak apps and shared runtimes. Checks on startup and explicit Check again requests refresh the native cache normally; periodic native checks use the host's current metadata. Flatpak checks query configured user and system installations. A partially unknown update state does not show an all-current result. Desktop notifications are deduplicated by update list. Updates never install automatically.

The sidebar badge and tray indicator show detected updates. A desktop may keep its launcher/taskbar icon static. Tray support and background permission depend on your desktop/extension. Settings and the in-app update count remain available independently.

Add all updates to Downloads gathers both native and Flatpak updates; Arch-family systems reject selected subsets through this update flow. Native plans are simulated before application. Host-reported progress and restart/sign-out advice remain available. No automatic reboot or rollback is performed.

## Flatpak app management

Open Flatpak apps to search, list installed apps, view app/runtime updates, and inspect sources. User and system installations are labeled Just me and All users. Native app overviews also provide a Find Flatpak search option.

You can install a selected app, remove it while keeping app data, queue individual updates or all currently available apps/runtimes in one selected installation, or explicitly add the canonical Flathub source for your account. Flatpak updates now go into Downloads, where selections can be removed before review. System changes and Flatpak updates share the queue screen but have separate review/apply actions. Only explicit queued Flatpak references are submitted; completed scope batches are removed and failed/unattempted batches remain queued. Forge does not replace existing sources, disable signature checking, delete app data, or run an unused-runtime cleanup. Named/custom Flatpak installations beyond user and the default system installation are not supported yet.

Install confirmations include a summary of publisher-declared permissions and the original metadata. Scope, source, application ID, and branch are shown. Flatpak resolves runtimes and related components itself: the confirmation describes the selection, not a complete dependency simulation. System-wide operations depend on host authorization policy and may fail if interactive authentication or agreements cannot be completed. Errors are shown instead of silently bypassing authorization.

**Permission change:** the Flatpak now requests `org.freedesktop.Flatpak` session-bus access to execute the host Flatpak command through flatpak-spawn. This permission exposes a general host-command channel and is broader than filesystem isolation alone. Flatpak integration builds validated argument arrays. Storage uses a fixed host helper and allowlisted system maintenance commands. The catalog helper reads configured Flathub AppStream metadata and downloads bounded PNG/JPEG/WebP/JXL artwork only from HTTPS Flathub hosts; redirects use the same allowlist. First-run setup can run fixed prerequisite installers through pkexec and request the AppIndicator extension through GNOME’s extension service. None of these paths invoke a shell or sudo. This bridge is necessary for this implementation to manage the real host installation; it is not a claim of strict sandbox containment.

Live read-only installed/search/permission lookups passed, including the command bridge from the GNOME runtime. The update-and-queue flow has also passed with a real disposable Flatpak updated from a local fixture repository in an isolated installation. User app changes and source-changing commands remain untested on real user data. Real desktop login startup permission has likewise only been exercised with an isolated test portal.

## Storage & Cleanup

Storage now follows Stacer-style categories: package caches, application caches, application logs, crash reports, and Trash. It is a storage-reclamation tool, not a RAM/CPU booster. Nothing is preselected or cleaned automatically.

- The read-only scan looks in conventional user cache/state folders, Flatpak app cache folders, and the user's Trash. Downloads, Documents, browser profiles, saved passwords, app settings, and installed program files are outside its deletion locations.
- Application caches are eligible after 7 days without modification. Current `.log`/lock files and current files in log directories are excluded. Rotated user logs and user crash files/metadata require 30 days.
- Trash deletion is permanent. Only scanned entries are candidates; nested empty directories and links can be removed without following link targets.
- Before user cleanup, Forge previews the category selection and requires acknowledgment. The host helper rechecks file identities and timestamps and uses directory-relative, no-follow file operations. Changed, replaced, inaccessible, or no-longer-eligible files are skipped.
- Package cache maintenance uses administrator-authorized fixed commands: APT clean, DNF clean packages, or paccache retaining three versions on Arch when installed. Downloaded packages may need to be fetched again. The manager decides the final result; scan estimates may be partial.
- Old system journals use administrator-authorized journalctl vacuum with a 30-day retention rule; current journals are preserved. Protected `/var/crash`, systemd coredump, and ABRT locations are shown as excluded from user cleanup, not deleted by this build.

The cleanup helper runs on the host as the current user through the existing host-command channel. Only the fixed package-manager/journal commands request elevation through pkexec. The GUI never runs as root, and no arbitrary shell command or generic privileged file-deletion helper is used.

File-size totals describe listed data and are not a guarantee of uniquely reclaimed filesystem space. Scan again after cleanup to refresh free space. Caches may be regenerated, require downloads, or make the next app launch slower. The safety tests delete temporary fixtures only. Real user cleanup and privileged system maintenance have not been run during development.

## Guardrails and limitations

Forge simulates native package changes before asking for approval. Known core removals are blocked, including selected boot, base-system, package manager, APT/dpkg and pacman packages. Desktop/login removals, downgrades, core changes, and large plans are called out. Destructive plans require explicit acknowledgment. Empty plans are blocked. Removal requests disable automatic dependency removal and autoremove.

These are conservative heuristics, not complete dependency analysis or a guarantee of a bootable system. The host resolves again when applying, so changes to metadata can affect the plan. Forge provides no automatic backup or rollback. An error can occur after some changes have completed; Forge retains selections and asks you to recheck installed packages/updates before retrying.

The Library includes system packages as well as apps. Native transactions, repository writes, Flatpak-changing operations, polkit authentication, and real login/background behavior still need end-to-end testing on disposable systems. Fedora read-only search/update checks and GUI tests have passed. Ubuntu and Arch detection, presentation, and package mapping are tested in code, not on real machines. Only an x86_64 Flatpak bundle is supplied here.

AUR, Snap, PPAs, Windows `.exe`/`.msi` installation, release upgrades, localization, a complete AppStream-driven catalog, transaction history, a signed update channel, and automatic rollback are also not included. Immutable distributions need their own supported native-system workflow.

## Source and checks

Requires Python 3, PyGObject, GTK 4.8+ and libadwaita 1.2+.

```sh
python3 forge.py --demo
python3 -m unittest discover -s tests -v
python3 -m py_compile forge.py tray.py flatpaks.py startup.py cleaner.py cleanup_host.py catalog.py catalog_host.py requirements.py prepare_appstream.py
```

Demo mode uses labeled sample data, disables package changes and startup changes, and does not schedule update monitoring. Source demo preferences are per user; no real transactions are exercised by the unit tests.

For development builds, install flatpak-builder and the GNOME runtime/SDK first, then:

```sh
flatpak-builder --user --force-clean --repo=repo build io.github.jmlp0818.Forge.json
flatpak build-bundle --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo repo Forge.flatpak io.github.jmlp0818.Forge
```

The application ID is provisional. Public distribution still needs an owned ID, artwork-license review, project/support URLs, screenshots, distro/accessibility testing, and a signed release/update process.

## References and license

- [PackageKit transaction API](https://www.freedesktop.org/software/PackageKit/doc/dbus-org.freedesktop.packagekit1.Transaction.html)
- [PackageKit security](https://www.freedesktop.org/software/PackageKit/doc/security.html)
- [Flatpak manifests](https://docs.flatpak.org/en/latest/manifests.html)
- [GNOME AppIndicator support](https://extensions.gnome.org/extension/615/appindicator-support/)
- [StatusNotifierItem specification](https://www.freedesktop.org/wiki/Specifications/StatusNotifierItem/)

Forge code and original icon: MIT; see LICENSE. AppStream metadata: CC0-1.0. Third-party application artwork retains its upstream terms and is excluded from Forge's MIT license.
