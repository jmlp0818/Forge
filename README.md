# Forge

A Linux app browser, package updater, and storage cleanup tool built with GTK 4 and libadwaita.

## Download

**[Download Forge 0.14.0 for Linux x86_64](https://github.com/jmlp0818/Forge/releases/download/v0.14.0/Forge-0.14.0.flatpak)**

[All releases and checksums](https://github.com/jmlp0818/Forge/releases)

This is a preview/test build. Windows, macOS, and ARM installers are not provided.

## Install

Flatpak must be installed. Open the downloaded `.flatpak` file with your software installer. It may also download GNOME Platform 51.

Alternatively, from your download folder:

```sh
flatpak install --user ./Forge-0.14.0.flatpak
flatpak run io.github.forge.PackageManager
```

Native package operations require a working host PackageKit backend. Forge checks prerequisites at first launch and under Settings → Check setup.

## Features

- Browse app suggestions and search native repositories.
- Manage Flatpak apps and review app/system updates in a shared Downloads queue.
- Check periodically for updates while Forge is running.
- Scan storage cleanup categories and review selections before deleting.
- Choose appearance, login startup, and background behavior.

Updates require review; Forge does not automatically install them. Check Releases for newer Forge builds; this download does not configure automatic updates for Forge itself.

## Preview limitations

An isolated Flatpak update and Forge installation were tested during development. Real user app/system updates, Ubuntu/Arch behavior, interrupted-operation recovery, and rollback remain unverified. No rollback feature is included.

Forge uses broad Flatpak host-command access for package management, setup, and cleanup. Administrator authentication may be required for system changes. Tray support varies by desktop.

## Feedback

[Report an issue](https://github.com/jmlp0818/Forge/issues) with your distribution, desktop, Forge version, and steps to reproduce. Remove private information from reports.
