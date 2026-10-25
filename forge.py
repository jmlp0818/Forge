#!/usr/bin/env python3
"""Forge: a native PackageKit frontend. No shell or privilege escalation helpers."""
import sys
import json
import os
import re
import unicodedata
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk, Gio, GLib, Gdk
from tray import Tray
from startup import Startup
from cleaner import Cleaner
from catalog import Catalog
from requirements import Requirements
from operations import OperationJournal
from flatpaks import Flatpaks, app_ref, permissions_summary

APP_ID = 'io.github.jmlp0818.Forge'
VERSION = '0.15.0'
SERVICE = 'org.freedesktop.PackageKit'
TX = SERVICE + '.Transaction'
DEMO = '--demo' in sys.argv
def parse_os_release(text):
    values = {}
    for line in text.splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key] = value.strip().strip('"').strip("'")
    return values

def host_distribution(paths=None):
    if paths is None:
        paths = [Path('/run/host/os-release')] if Path('/.flatpak-info').exists() else [Path('/etc/os-release')]
    for path in paths:
        try:
            values = parse_os_release(Path(path).read_text())
            distro_id = values.get('ID', 'unknown')
            ids = {distro_id, *values.get('ID_LIKE', '').split()}
            family = 'arch' if 'arch' in ids else 'ubuntu' if ids & {'ubuntu', 'debian'} else 'fedora' if 'fedora' in ids else 'other'
            return {'id': distro_id, 'family': family, 'name': values.get('PRETTY_NAME', distro_id), 'version': values.get('VERSION_ID', ''), 'codename': values.get('VERSION_CODENAME', '')}
        except OSError: continue
    return {'id': 'unknown', 'family': 'other', 'name': 'Unknown Linux host', 'version': '', 'codename': ''}

def distro_sources(host):
    # Suggestions describe source groups. Only real RepoDetail IDs may be toggled.
    profiles = {
        'fedora': [('Fedora base and updates', 'Official Fedora sources for your installed release. Existing sources appear above.'),
                   ('Fedora third-party sources', 'Optional RPM Fusion, Chrome, Steam, and driver sources are listed below.')],
        'ubuntu': [('Ubuntu official archives', 'Main, Universe, Restricted, and Multiverse are components of Ubuntu archive sources. The host reports their configured source entries above.'),
                   ('Ubuntu updates and security', 'Use updates and security sources for your installed Ubuntu release. Forge does not switch your release or add a different release’s sources.')],
        'arch': [('Arch core and extra', 'Official rolling-release repositories. Existing repository IDs appear above with their actual state.'),
                 ('Arch multilib', 'Optional 32-bit packages on x86_64. It can be enabled above if your host has a configured multilib source.')],
    }
    return list(profiles.get(host['family'], [('Your distribution’s repositories', 'Only sources reported by your host package service are shown. Forge does not assume Fedora, Ubuntu, or Arch repository formats for this host.')]))

NATIVE_NAMES = {
    'arch': {'libreoffice-writer': 'libreoffice-fresh', 'libreoffice-calc': 'libreoffice-fresh',
             'libreoffice-impress': 'libreoffice-fresh', 'minetest': 'luanti'},
}

def native_package_names(names, family):
    return list(dict.fromkeys(NATIVE_NAMES.get(family, {}).get(name, name) for name in names))

REPO_CATALOG = [
    ('RPM Fusion Free', 'rpmfusion-free', 'Community software and multimedia tools.', 'https://rpmfusion.org/Configuration'),
    ('RPM Fusion Nonfree', 'rpmfusion-nonfree', 'Additional software with nonfree licenses.', 'https://rpmfusion.org/Configuration'),
    ('Google Chrome', 'google-chrome', 'Google’s proprietary browser.', 'https://docs.fedoraproject.org/en-US/workstation-working-group/third-party-repos/'),
    ('Steam', 'rpmfusion-nonfree-steam', 'RPM Fusion’s limited Steam repository.', 'https://docs.fedoraproject.org/en-US/workstation-working-group/third-party-repos/'),
    ('NVIDIA drivers', 'rpmfusion-nonfree-nvidia-driver', 'RPM Fusion’s limited driver repository.', 'https://docs.fedoraproject.org/en-US/workstation-working-group/third-party-repos/'),
]


# Editorial collections; availability and versions are resolved from the host on click.
DISCOVER_APPS = {
    'gimp': ('GIMP', 'Retouch photos and make something original.', 'applications-graphics-symbolic'),
    'inkscape': ('Inkscape', 'Turn ideas into crisp vector artwork.', 'draw-freehand-symbolic'),
    'blender': ('Blender', 'Model, animate, and explore 3D creation.', 'applications-graphics-symbolic'),
    'krita': ('Krita', 'A canvas for digital painting and illustration.', 'applications-graphics-symbolic'),
    'git': ('Git', 'Keep your code and projects moving forward.', 'applications-development-symbolic'),
    'neovim': ('Neovim', 'Build your own keyboard-driven editor.', 'accessories-text-editor-symbolic'),
    'meld': ('Meld', 'Compare files and see exactly what changed.', 'view-dual-symbolic'),
    'cmake': ('CMake', 'Configure and build your next project.', 'applications-engineering-symbolic'),
    'vlc': ('VLC', 'A versatile player for your media library.', 'multimedia-video-player-symbolic'),
    'audacity': ('Audacity', 'Record, edit, and shape your audio.', 'audio-input-microphone-symbolic'),
    'mpv': ('mpv', 'A focused video player with a minimal interface.', 'media-playback-start-symbolic'),
    'obs-studio': ('OBS Studio', 'Capture your screen and produce live streams.', 'camera-video-symbolic'),
    'firefox': ('Firefox', 'Browse the web with an extensible browser.', 'web-browser-symbolic'),
    'thunderbird': ('Thunderbird', 'Bring your mail and calendars together.', 'mail-unread-symbolic'),
    'libreoffice-writer': ('LibreOffice Writer', 'Create documents, letters, and reports.', 'x-office-document-symbolic'),
    'keepassxc': ('KeePassXC', 'Organize passwords in a local vault.', 'dialog-password-symbolic'),
    'htop': ('htop', 'See what is happening under the hood.', 'utilities-system-monitor-symbolic'),
    'btop': ('btop', 'Explore system resources from your terminal.', 'utilities-system-monitor-symbolic'),
    'filelight': ('Filelight', 'Find out where your disk space went.', 'drive-harddisk-symbolic'),
    'fastfetch': ('Fastfetch', 'Get a quick overview of your system.', 'computer-symbolic'),
    'supertuxkart': ('SuperTuxKart', 'Take a break with arcade kart racing.', 'input-gaming-symbolic'),
    'wesnoth': ('Battle for Wesnoth', 'Plan your next move in a fantasy strategy game.', 'input-gaming-symbolic'),
    'minetest': ('Luanti / Minetest', 'Explore a voxel world and make it your own.', 'input-gaming-symbolic'),
    'lutris': ('Lutris', 'Organize your Linux gaming library.', 'input-gaming-symbolic'),
}
COLLECTIONS = {
    'Creative': ('applications-graphics-symbolic', 'Make your next great thing', ['gimp', 'inkscape', 'blender', 'krita']),
    'Development': ('applications-development-symbolic', 'Tools for your next project', ['git', 'neovim', 'meld', 'cmake']),
    'Media': ('multimedia-video-player-symbolic', 'Watch, record, and create', ['vlc', 'audacity', 'mpv', 'obs-studio']),
    'Everyday': ('applications-office-symbolic', 'A comfortable daily setup', ['firefox', 'thunderbird', 'libreoffice-writer', 'keepassxc']),
    'System tools': ('utilities-system-monitor-symbolic', 'Get to know your machine', ['htop', 'btop', 'filelight', 'fastfetch']),
    'Gaming': ('input-gaming-symbolic', 'Make room for a little play', ['supertuxkart', 'wesnoth', 'minetest', 'lutris']),
}
DISCOVER_APPS.update({
    'calibre': ('Calibre', 'Organize and read your ebook collection.', 'accessories-dictionary-symbolic'),
    'stellarium': ('Stellarium', 'Explore the night sky and learn about space.', 'weather-clear-night-symbolic'),
    'tuxpaint': ('Tux Paint', 'Draw and experiment with a playful painting app.', 'applications-graphics-symbolic'),
    'geogebra': ('GeoGebra', 'Explore geometry and mathematics interactively.', 'accessories-calculator-symbolic'),
    'orca': ('Orca', 'Read supported desktop interfaces with speech or braille.', 'preferences-desktop-accessibility-symbolic'),
    'espeak-ng': ('eSpeak NG', 'Convert text to synthesized speech.', 'audio-speakers-symbolic'),
    'onboard': ('Onboard', 'Explore an on-screen keyboard for supported desktops.', 'input-keyboard-symbolic'),
    'okular': ('Okular', 'Read documents and annotate PDF files.', 'x-office-document-symbolic'),
    'gnome-text-editor': ('Text Editor', 'Write notes and edit text with a focused interface.', 'accessories-text-editor-symbolic'),
    'libreoffice-calc': ('LibreOffice Calc', 'Work with spreadsheets, budgets, and tables.', 'x-office-spreadsheet-symbolic'),
    'libreoffice-impress': ('LibreOffice Impress', 'Prepare slides and presentations.', 'x-office-presentation-symbolic'),
    'evolution': ('Evolution', 'Manage email, calendars, and contacts together.', 'x-office-calendar-symbolic'),
})
COLLECTIONS.update({
    'Learning': ('applications-science-symbolic', 'Read, explore, and learn', ['calibre', 'stellarium', 'tuxpaint', 'geogebra']),
    'Accessibility': ('preferences-desktop-accessibility-symbolic', 'Explore assistive tools', ['orca', 'espeak-ng', 'onboard', 'okular']),
    'Work & study': ('applications-office-symbolic', 'Write, calculate, and present', ['gnome-text-editor', 'libreoffice-writer', 'libreoffice-calc', 'libreoffice-impress']),
    'Communication': ('mail-unread-symbolic', 'Stay connected and organized', ['thunderbird', 'evolution', 'firefox', 'keepassxc']),
})
APP_NOTES = {
    'orca': 'After installation, enable the screen reader in your desktop accessibility settings. Support depends on your desktop session and the applications you use.',
    'onboard': 'On-screen keyboard support depends on your display server and desktop. Check your desktop’s built-in accessibility keyboard first, especially on Wayland.',
    'espeak-ng': 'This is a speech engine, not a complete screen reader. Other applications or desktop settings may be needed to use it.',
    'geogebra': 'Availability varies by distribution and repository. A missing package does not mean the app is unavailable through other sources.',
    'keepassxc': 'A local password vault. Back up your database and remember its master password; Forge cannot recover it.',
    'obs-studio': 'Screen and audio capture depend on your desktop’s permissions and available capture services.',
    'vlc': 'Supported media formats depend on the build and codecs supplied by your software sources.',
}
TASK_TAGS = {
    'gimp': 'edit photo picture image retouch photoshop alternative',
    'inkscape': 'draw vector logo design illustrator alternative',
    'blender': '3d model animate render animation',
    'krita': 'draw paint art illustration digital',
    'git': 'code version control developer programming',
    'neovim': 'code text editor vim terminal programming',
    'meld': 'compare diff file code merge',
    'cmake': 'code build compile programming',
    'vlc': 'watch video movie play music media',
    'mpv': 'watch video movie player',
    'audacity': 'edit audio record sound podcast music',
    'obs-studio': 'record screen stream broadcast video',
    'firefox': 'browse web internet browser',
    'thunderbird': 'email mail calendar contact',
    'evolution': 'email mail calendar contact organize',
    'libreoffice-writer': 'write document essay word alternative office homework',
    'libreoffice-calc': 'spreadsheet budget table excel alternative finance',
    'libreoffice-impress': 'presentation slide powerpoint alternative',
    'gnome-text-editor': 'write note text editor notepad alternative',
    'keepassxc': 'password vault privacy offline security',
    'htop': 'monitor process cpu memory system terminal',
    'btop': 'monitor resource cpu memory system terminal',
    'filelight': 'disk space storage cleanup',
    'fastfetch': 'system info hardware terminal',
    'supertuxkart': 'game play racing family kart',
    'wesnoth': 'game play strategy fantasy turn based',
    'minetest': 'game play voxel world build minecraft alternative',
    'lutris': 'game library launcher play',
    'calibre': 'read ebook book library kindle',
    'stellarium': 'learn astronomy space sky star planet science',
    'tuxpaint': 'draw paint art child kid family learn',
    'geogebra': 'learn math geometry algebra school homework',
    'orca': 'screen reader accessibility speech blind braille',
    'espeak-ng': 'text speech voice accessibility read aloud',
    'onboard': 'screen keyboard accessibility typing',
    'okular': 'read pdf annotate document ebook',
}
SEARCH_STOPWORDS = {'i', 'a', 'an', 'the', 'to', 'for', 'my', 'me', 'with', 'want', 'need', 'app', 'apps', 'please', 'can', 'that', 'something', 'find', 'how', 'do', 'get', 'use', 'software', 'program', 'tool', 'help', 'you'}
SEARCH_ALIASES = {'photos': 'photo', 'pictures': 'photo', 'images': 'image', 'editing': 'edit', 'ebooks': 'ebook', 'books': 'book', 'games': 'game', 'movies': 'movie', 'videos': 'video', 'documents': 'document', 'notes': 'note', 'slides': 'slide', 'passwords': 'password', 'spreadsheets': 'spreadsheet'}

def search_tokens(text):
    folded = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    return {SEARCH_ALIASES.get(word, word) for word in re.findall(r'\w+', folded) if word not in SEARCH_STOPWORDS}

def catalog_matches(query, limit=12):
    terms = search_tokens(query)
    if not terms: return []
    ranked = []
    for name, (title, summary, icon) in DISCOVER_APPS.items():
        words = search_tokens(' '.join((name, title, summary, TASK_TAGS.get(name, ''))))
        if all(any(word.startswith(term) for word in words) for term in terms):
            score = 100 if query.strip().casefold() in (name.casefold(), title.casefold()) else len(terms & search_tokens(name + ' ' + title))
            ranked.append((-score, title.casefold(), name))
    return [item[2] for item in sorted(ranked)[:limit]]

WINDOWS_ALTERNATIVES = [
    ('Microsoft Word, Excel & PowerPoint', 'Write documents, work with spreadsheets, and make presentations.', ['libreoffice-writer', 'libreoffice-calc', 'libreoffice-impress'], 'LibreOffice is an alternative, not an exact replacement. Test complex documents, macros, and formatting before relying on them.'),
    ('Photoshop & digital painting', 'Edit photos or make illustrations.', ['gimp', 'krita', 'inkscape'], 'Choose GIMP for image editing, Krita for painting, or Inkscape for vector artwork. Workflows, file support, and plugins differ from Adobe apps.'),
    ('Windows Media Player', 'Watch videos and listen to local media.', ['vlc', 'mpv'], 'Supported formats depend on the player build and codecs available from your software sources.'),
    ('Notepad', 'Write notes and edit plain text.', ['gnome-text-editor'], 'Text Editor provides a simple text-editing workflow; it is not a word processor.'),
    ('Paint & drawing', 'Draw, paint, and experiment.', ['krita', 'tuxpaint'], 'Krita provides a full illustration workspace; Tux Paint is a playful drawing app geared toward children.'),
    ('Email & calendars', 'Keep mail, calendars, and contacts together.', ['thunderbird', 'evolution'], 'Account compatibility and import options depend on your mail provider. No account data is migrated by Forge.'),
]

def package_presentation(name, version, arch, repo, summary, technical=False):
    title = DISCOVER_APPS.get(name, (name,))[0]
    if technical:
        return title, f'{summary}\n{name} · {version} · {arch} · {repo}'
    return title, summary + ('\nSystem package · ' + repo if repo else '\nSystem package')

FEATURED = ['gimp', 'vlc', 'inkscape']

APP_ICON_ROOTS = [Path(__file__).resolve().parent / 'data' / 'app-icons',
                  Path(__file__).resolve().parent.parent / 'share' / 'forge' / 'app-icons']
_ICON_TEXTURES = {}

def app_icon_path(name, roots=None):
    # Repository package names are untrusted; never turn them into arbitrary paths.
    if name not in DISCOVER_APPS: return None
    for root in APP_ICON_ROOTS if roots is None else roots:
        candidate = Path(root) / (name + '.png')
        if candidate.is_file(): return candidate
    return None

def app_icon(name, size=32):
    path = app_icon_path(name)
    if path:
        try:
            if str(path) not in _ICON_TEXTURES:
                _ICON_TEXTURES[str(path)] = Gdk.Texture.new_from_filename(str(path))
            image = Gtk.Image.new_from_paintable(_ICON_TEXTURES[str(path)])
            image.set_pixel_size(size)
            return image
        except GLib.Error:
            pass  # Missing or damaged artwork should never break package browsing.
    fallback = DISCOVER_APPS.get(name, ('', '', 'application-x-executable-symbolic'))[2]
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    image = Gtk.Image(icon_name=name if theme.has_icon(name) else fallback, pixel_size=size)
    image.add_css_class('repo-icon')
    return image

def collection_names(category):
    return list(COLLECTIONS[category][2])

def repository_state(repo_id, repos):
    if repo_id not in repos: return 'Not configured'
    return 'Enabled' if repos[repo_id][1] else 'Disabled'

APPEARANCE_DEFAULTS = {'scheme': 'dark', 'accent': 'indigo', 'compact': False, 'technical_details': False, 'update_notifications': True, 'tray_background': False, 'launch_at_login': False, 'start_minimized': True, 'check_on_startup': True, 'check_interval': 30, 'close_action': 'quit'}
SCHEMES = [('system', 'Follow system'), ('light', 'Light'), ('dark', 'Dark')]
ACCENTS = [('indigo', 'Forge indigo'), ('teal', 'Teal'), ('blue', 'Ocean blue'), ('orange', 'Ember orange'), ('rose', 'Rose')]
ACCENT_COLORS = {
    'indigo': ('#5668b8', '#bcc8ff', '#34416a', '#e2e7ff'),
    'teal': ('#16705f', '#88ddc6', '#234e47', '#d4eee6'),
    'blue': ('#2363b0', '#9ccaff', '#253e5b', '#dceaff'),
    'orange': ('#a44c16', '#ffc08e', '#583e2c', '#ffeadb'),
    'rose': ('#a13a68', '#f6afd1', '#563047', '#fbe0ee'),
}

def clean_appearance(values):
    values = values if isinstance(values, dict) else {}
    return {
        'scheme': values.get('scheme') if isinstance(values.get('scheme'), str) and values.get('scheme') in dict(SCHEMES) else APPEARANCE_DEFAULTS['scheme'],
        'accent': values.get('accent') if isinstance(values.get('accent'), str) and values.get('accent') in ACCENT_COLORS else APPEARANCE_DEFAULTS['accent'],
        'compact': values.get('compact') if type(values.get('compact')) is bool else False,
        'technical_details': values.get('technical_details') if type(values.get('technical_details')) is bool else False,
        'update_notifications': values.get('update_notifications') if type(values.get('update_notifications')) is bool else True,
        'tray_background': values.get('tray_background') if type(values.get('tray_background')) is bool else False,
        'launch_at_login': values.get('launch_at_login') if type(values.get('launch_at_login')) is bool else False,
        'start_minimized': values.get('start_minimized') if type(values.get('start_minimized')) is bool else True,
        'check_on_startup': values.get('check_on_startup') if type(values.get('check_on_startup')) is bool else True,
        'check_interval': values.get('check_interval') if type(values.get('check_interval')) is int and values.get('check_interval') in (0,15,30,60,240,1440) else 30,
        'close_action': values.get('close_action') if isinstance(values.get('close_action'), str) and values.get('close_action') in ('quit','minimize','tray') else ('tray' if values.get('tray_background') is True else 'quit'),
    }

class AppearanceSettings:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(GLib.get_user_config_dir()) / 'forge' / 'appearance.json'

    def load(self):
        try: return clean_appearance(json.loads(self.path.read_text()))
        except (OSError, ValueError): return dict(APPEARANCE_DEFAULTS)

    def save(self, values):
        cleaned = clean_appearance(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(cleaned))
        temporary.replace(self.path)


def appearance_css(values, dark):
    values = clean_appearance(values)
    accent, bright, dark_tint, light_tint = ACCENT_COLORS[values['accent']]
    bg, side, surface, ink, secondary, border = ('#17191f', '#111318', '#252936', '#f4f5fa', '#bfc5d4', '#3a4152') if dark else ('#f5f6fa', '#eaedf5', '#ffffff', '#202432', '#505b6e', '#cbd2e1')
    tint = dark_tint if dark else light_tint
    accent_ink = bright if dark else accent
    row_padding, tile_padding, hero_padding = (2, 12, 18) if values['compact'] else (8, 20, 26)
    return f"""
    @define-color accent_bg_color {accent};
    @define-color accent_fg_color white;
    @define-color accent_color {accent_ink};
    window {{ background: {bg}; color: {ink}; }}
    .sidebar {{ background: {side}; }}
    .brand, .eyebrow, .repo-icon, .section {{ color: {accent_ink}; }}
    .subtitle, .tile-copy {{ color: {secondary}; }}
    .hero {{ background: linear-gradient(115deg, {tint}, {surface}); color: {ink}; padding: {hero_padding}px; }}
    .card, .app-tile, .category-tile {{ background: {surface}; color: {ink}; border-color: {border}; }}
    .app-tile {{ padding: {tile_padding}px; }}
    .app-tile:hover, .category-tile:hover {{ background: {tint}; border-color: {accent_ink}; }}
    .active, .pill, .setup-banner {{ background: {tint}; color: {accent_ink}; }}
    .suggested-action {{ background: {accent}; color: white; }}
    list.boxed-list > row {{ padding: {row_padding}px 6px; }}
    .nav {{ padding: {8 if values['compact'] else 12}px; }}
    .category-tile {{ padding: {10 if values['compact'] else 16}px; }}
    .mint {{ color: {'#96dbc6' if dark else '#176653'}; }}
    .peach {{ color: {'#efb58d' if dark else '#9a4b1a'}; }}
    .lavender {{ color: {'#b6b4f4' if dark else '#6050a3'}; }}
    """

class SetupState:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(GLib.get_user_config_dir()) / 'forge' / 'setup.json'

    def complete(self):
        try: return json.loads(self.path.read_text()).get('repository_setup_seen') is True
        except (OSError, ValueError, AttributeError): return False

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'repository_setup_seen': True}))
        temporary.replace(self.path)


def package_parts(package_id):
    parts = package_id.split(';')
    return (parts + ['', '', '', ''])[:4]

def transaction_args(action, ids, simulate=False):
    flags = 2 | (4 if simulate else 0)  # only-trusted; simulate
    if action == 'RemovePackages':
        return GLib.Variant('(tasbb)', (flags, ids, False, False))
    return GLib.Variant('(tas)', (flags, ids))

# Conservative guardrails, not a complete substitute for the host's protections.
CORE_EXACT = {'bash', 'coreutils', 'filesystem', 'setup', 'glibc', 'rpm', 'dnf',
              'dnf5', 'PackageKit', 'NetworkManager', 'systemd', 'sudo', 'polkit',
              'apt', 'dpkg', 'base-files', 'base-passwd', 'libc6', 'libc-bin', 'init',
              'ubuntu-minimal', 'ubuntu-standard', 'pacman', 'archlinux-keyring',
              'linux', 'linux-lts', 'linux-zen', 'linux-hardened', 'mkinitcpio', 'dracut'}
CORE_PREFIXES = ('kernel-', 'grub2', 'shim-', 'systemd-', 'glibc-', 'rpm-',
                 'dnf-', 'dnf5-', 'fedora-release', 'linux-image-', 'linux-modules-', 'grub-', 'shim-signed')
DESKTOP_EXACT = {'gnome-shell', 'gnome-session', 'plasma-desktop', 'plasma-workspace',
                 'kwin', 'sddm', 'gdm', 'lightdm', 'xorg-x11-server-Xorg'}
INFO_LABELS = {11: 'Update', 12: 'Install', 13: 'Remove', 15: 'Replace / obsolete',
               19: 'Reinstall', 20: 'Downgrade', 21: 'Prepare'}

def is_core_package(name):
    return name in CORE_EXACT or name == 'kernel' or name.startswith(CORE_PREFIXES)

def assess_plan(action, ids, results):
    requested = {package_parts(pid)[0] for pid in ids}
    removed = set(requested) if action == 'RemovePackages' else set()
    changed = set(requested)
    lines = []
    entries = []
    downgrades = []
    for kind, values in results:
        if kind != 'Package': continue
        info, pid, summary = values
        name, version, arch, repo = package_parts(pid)
        changed.add(name)
        if info in (13, 15): removed.add(name)
        if info == 20: downgrades.append(name)
        lines.append(f'{INFO_LABELS.get(info, "Change")} · {name} {version} · {arch} · {repo}')
        entries.append({'name': name, 'action': INFO_LABELS.get(info, 'Change'), 'version': version, 'arch': arch, 'repo': repo})
    blocked = sorted(name for name in removed if is_core_package(name))
    warnings = []
    if removed:
        warnings.append('This removes system packages. Applications that rely on them may stop working. Forge does not provide automatic rollback.')
    if removed & DESKTOP_EXACT:
        warnings.append('Desktop or login components will be removed. You could lose your graphical desktop or be unable to sign in.')
    if any(is_core_package(name) for name in changed) and not blocked:
        warnings.append('This changes core system components. Save your work and keep the computer powered on. A restart may be needed.')
    if downgrades:
        warnings.append('Downgrades were detected: ' + ', '.join(sorted(set(downgrades))) + '. Older versions may be incompatible with other packages.')
    if len(changed) >= 30:
        warnings.append(f'This is a large transaction affecting at least {len(changed)} package names. Review the complete list carefully.')
    return {'blocked': blocked, 'warnings': warnings, 'destructive': bool(removed or downgrades),
            'lines': sorted(set(lines)), 'entries': entries, 'removed': sorted(removed)}

def restart_message(results):
    values = {v[0] for k, v in results if k == 'RequireRestart'}
    if values & {4, 6}: return 'Changes applied. The package service recommends restarting the computer. Save your work first.'
    if values & {3, 5}: return 'Changes applied. The package service recommends signing out and back in. Save your work first.'
    if 2 in values: return 'Changes applied. Restart the affected applications to use the updates.'
    return 'Changes applied successfully. The host reported no restart request.'

def combined_update_count(native, flatpak):
    known = sum(value or 0 for value in (native, flatpak))
    return known if known or (native is not None and flatpak is not None) else None

class UpdateState:
    def __init__(self):
        self.ids = None

    def accept(self, results, error=None):
        if error: return False
        ids = tuple(sorted({values[1] for kind, values in results if kind == 'Package'}))
        changed = ids != self.ids
        self.ids = ids
        return changed and bool(ids)

    @property
    def count(self): return None if self.ids is None else len(self.ids)

class Backend:
    def __init__(self, status, progress=None, interactive=True, journal=None):
        self.status = status
        self.progress = progress
        self.interactive = interactive
        self.hints_type = None
        self.bus = None
        self.busy = False
        self.journal = journal

    def run(self, method, args, done, interactive=None):
        if self.busy:
            done([], 'Another operation is running. Please wait.')
            return
        self.busy = True
        writing = method in ('InstallPackages', 'RemovePackages', 'UpdatePackages', 'RepoEnable') and not (method != 'RepoEnable' and args.unpack()[0] & 4)
        if writing and self.journal:
            try: self.journal.begin(method)
            except OSError as error:
                self.busy = False
                done([], 'Cannot record the operation safely: ' + str(error))
                return
        results, errors = [], []
        subscription = [None]
        properties_subscription = [None]
        owner_subscription = [None]
        finished = [False]
        def finish(error=None):
            if finished[0]: return
            finished[0] = True
            if subscription[0] is not None:
                self.bus.signal_unsubscribe(subscription[0])
            if properties_subscription[0] is not None:
                self.bus.signal_unsubscribe(properties_subscription[0])
            if owner_subscription[0] is not None:
                self.bus.signal_unsubscribe(owner_subscription[0])
            self.busy = False
            error = error or ('\n'.join(errors) if errors else None)
            if writing and self.journal: self.journal.finish(error)
            done(results, error)
        def signal(bus, sender, path, interface, name, params, *unused):
            if finished[0]: return
            values = params.unpack()
            if name in ('Package', 'RepoDetail', 'Details', 'RequireRestart'):
                results.append((name, values))
                if name == 'Package':
                    progress_action = {10: 'Downloading', 11: 'Updating', 12: 'Installing', 13: 'Removing'}.get(values[0])
                    if progress_action:
                        self.status(progress_action + ' ' + package_parts(values[1])[0] + '…')
            elif name == 'ErrorCode':
                errors.append(values[1])
            elif name == 'Finished':
                finish(None if values[0] == 1 else 'Transaction did not complete successfully.' if not errors else '\n'.join(errors))
            elif name == 'Changed':
                self.status('Working with the package service…')
        def properties_changed(bus, sender, path, interface, name, params, *unused):
            tx_interface, values, invalidated = params.unpack()
            percent = values.get('Percentage')
            if self.progress and tx_interface == TX and isinstance(percent, int):
                self.progress(percent if 0 <= percent <= 100 else None)
        def invoked(bus, result, *unused):
            try: bus.call_finish(result)
            except GLib.Error as e: finish(e.message)
        def created(bus, result, *unused):
            if finished[0]: return
            try:
                path = bus.call_finish(result).unpack()[0]
                subscription[0] = bus.signal_subscribe(SERVICE, TX, None, path, None, Gio.DBusSignalFlags.NONE, signal)
                if self.progress:
                    properties_subscription[0] = bus.signal_subscribe(SERVICE, 'org.freedesktop.DBus.Properties', 'PropertiesChanged', path, None, Gio.DBusSignalFlags.NONE, properties_changed)
                allow_prompt = self.interactive if interactive is None else interactive
                def invoke():
                    if finished[0]: return
                    bus.call(SERVICE, path, TX, method, args, None, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION if allow_prompt else Gio.DBusCallFlags.NONE, 120000, None, invoked)
                def hinted(connection, reply, *unused):
                    if finished[0]: return
                    try: connection.call_finish(reply)
                    except GLib.Error as error:
                        finish('Could not configure package authorization: ' + error.message);return
                    invoke()
                def set_hints():
                    hints = GLib.Variant('(a{sv})', ({'interactive': GLib.Variant('b', allow_prompt)},)) if self.hints_type == 'a{sv}' else GLib.Variant('(as)', (['interactive=' + str(allow_prompt).lower()],))
                    bus.call(SERVICE,path,TX,'SetHints',hints,None,Gio.DBusCallFlags.NONE,10000,None,hinted)
                def inspected(connection, reply, *unused):
                    if finished[0]: return
                    try:
                        import xml.etree.ElementTree as ET
                        xml=connection.call_finish(reply).unpack()[0]
                        node=ET.fromstring(xml).find("./interface[@name='"+TX+"']/method[@name='SetHints']/arg[@direction='in']")
                        self.hints_type=node.get('type') if node is not None else 'as'
                        set_hints()
                    except (GLib.Error,ET.ParseError) as error: finish('Could not inspect the package service: '+str(error))
                if self.hints_type: set_hints()
                else: bus.call(SERVICE,path,'org.freedesktop.DBus.Introspectable','Introspect',None,None,Gio.DBusCallFlags.NONE,10000,None,inspected)
            except GLib.Error as e: finish(e.message)
        def connected(source, result, *unused):
            try:
                self.bus = Gio.bus_get_finish(result)
                def owner_changed(bus, sender, path, interface, name, params, *unused):
                    service, previous, current = params.unpack()
                    if previous and previous != current:
                        finish('The package service restarted or disconnected. Some changes may have completed. Recheck Library and Updates before retrying.')
                owner_subscription[0] = self.bus.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged', '/org/freedesktop/DBus', SERVICE, Gio.DBusSignalFlags.NONE, owner_changed)
                self.bus.call(SERVICE, '/org/freedesktop/PackageKit', SERVICE, 'CreateTransaction', None, GLib.VariantType.new('(o)'), Gio.DBusCallFlags.NONE, 10000, None, created)
            except GLib.Error as e: finish('Cannot reach the host PackageKit service. ' + e.message)
        self.status('Connecting to the package service…')
        Gio.bus_get(Gio.BusType.SYSTEM, None, connected)

class Forge(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE if DEMO else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect('activate', self.activate)
        self.queue = {}
        self.flatpak_queue = {}
        self.operation_journals = {name: OperationJournal(name) for name in ('native', 'flatpak', 'cleanup')}
        self.cleaner = Cleaner(self.operation_journals['cleanup'])
        self.catalog = Catalog()
        self.requirements = Requirements()
        self.storage_scan = None
        self.storage_categories = set()
        self.page = 'Discover'
        self.backend = Backend(self.set_status, self.set_progress, journal=self.operation_journals['native'])
        self.monitor_backend = Backend(lambda text: None, interactive=False)
        self.update_state = UpdateState()
        self.flatpak_update_state = UpdateState()
        self.flatpaks = Flatpaks(self.set_status, journal=self.operation_journals['flatpak'])
        self.flatpak_monitor = Flatpaks()
        self.startup_manager = Startup(APP_ID, __file__)
        self.check_timer = None
        self.last_checked = 'Not checked this session'
        self.launch_background = '--background' in sys.argv
        self.available_updates = []
        self.background_hold = False
        self.locked = False
        self.generation = 0
        self.host = host_distribution()
        self.setup_state = SetupState()
        self.appearance_store = AppearanceSettings()
        self.appearance = self.appearance_store.load()

    def activate(self, app):
        if hasattr(self, 'win'):
            self.win.present()
            return
        css = Gtk.CssProvider()
        css.load_from_data(b'''
        window { background: #17191f; } .sidebar { background: #111318; }
        .brand { font-size: 25px; font-weight: 800; color: #a8b7ff; }
        .eyebrow { color: #a8b7ff; font-size: 11px; font-weight: 800; letter-spacing: 2px; }
        .hero { background: linear-gradient(115deg, #303b65, #252b40); border-radius: 18px; padding: 26px; }
        .hero-title { font-size: 30px; font-weight: 800; } .subtitle { color: #b4b8c8; }
        .card { background: #22252e; border-radius: 12px; padding: 8px; }
        .nav { padding: 12px; border-radius: 9px; } .active { background: #30384f; color: #c2cbff; }
        .pill { background: #30384f; border-radius: 7px; padding: 4px 9px; color: #b9c7ff; }
        .page-title { font-size: 24px; font-weight: 750; } .small { font-size: 12px; }
        list.boxed-list > row { padding: 8px 6px; } button { min-height: 30px; }
        .setup-banner { background: #27314a; border-radius: 12px; padding: 16px; }
        .app-tile { padding: 20px; border-radius: 14px; background: #252936; border: 1px solid #363c4d; }
        .app-tile:hover { background: #30384c; border-color: #879ad8; }
        .tile-title { font-size: 19px; font-weight: 750; }
        .tile-copy { color: #bdc3d4; font-size: 13px; }
        .category-tile { padding: 16px; border-radius: 12px; background: #222630; }
        .category-tile:hover { background: #30384b; }
        .mint { color: #96dbc6; } .peach { color: #efb58d; } .lavender { color: #b6b4f4; }
        .section-title { font-size: 19px; font-weight: 750; }
        .repo-icon { color: #9aabea; } .section { font-weight: 700; color: #b9c7ff; }
        
        ''')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.appearance_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.appearance_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        Adw.StyleManager.get_default().connect('notify::dark', lambda *args: self.refresh_appearance())
        self.apply_appearance()
        Gtk.Window.set_default_icon_name(APP_ID)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(Path(__file__).resolve().parent / 'data'))
        self.win = Adw.ApplicationWindow(application=self, title='Forge — Apps & Updates', default_width=1120, default_height=780)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label='FORGE  /  DISCOVER APPS', css_classes=['eyebrow']))
        outer.append(header)
        body = Gtk.Box()
        outer.append(body)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, width_request=210, css_classes=['sidebar'])
        for prop in ('margin_top','margin_bottom','margin_start','margin_end'): getattr(sidebar, 'set_'+prop)(16)
        sidebar.append(Gtk.Label(label='◈  Forge', xalign=0, css_classes=['brand'], margin_bottom=6))
        sidebar.append(Gtk.Label(label='Your system, thoughtfully managed.', wrap=True, xalign=0, css_classes=['subtitle','small'], margin_bottom=28))
        self.nav = {}
        for label, icon in [('Discover','system-search-symbolic'),('Installed','application-x-executable-symbolic'),('Updates','software-update-available-symbolic'),('Repositories','drive-harddisk-symbolic'),('Queue','view-list-symbolic'),('Flatpak apps','application-x-addon-symbolic'),('Storage','drive-harddisk-symbolic'),('Getting started','help-about-symbolic'),('Appearance','preferences-desktop-theme-symbolic')]:
            button = Gtk.Button(css_classes=['flat','nav'])
            row = Gtk.Box(spacing=12)
            nav_icon = Gtk.Image.new_from_icon_name(icon)
            row.append(nav_icon)
            if label == 'Updates': self.update_nav_icon = nav_icon
            nav_label=Gtk.Label(label={'Installed': 'Library', 'Queue': 'Downloads', 'Repositories': 'Software sources', 'Getting started': 'New to Linux', 'Appearance': 'Settings'}.get(label, label))
            row.append(nav_label)
            if label=='Queue':self.queue_nav_label=nav_label
            if label == 'Updates':
                self.update_badge = Gtk.Label(label='', visible=False, css_classes=['pill'])
                row.append(self.update_badge)
            button.set_child(row)
            button.connect('clicked', lambda b, p=label: self.navigate(p))
            sidebar.append(button)
            self.nav[label] = button
        spacer = Gtk.Box(vexpand=True)
        sidebar.append(spacer)
        sidebar.append(Gtk.Label(label='SYSTEM PACKAGES · ' + self.host['family'].upper(), xalign=0, css_classes=['eyebrow']))
        sidebar.append(Gtk.Label(label='Powered by PackageKit\n' + ('Demo · sample data' if DEMO else 'System authorization via polkit'), xalign=0, css_classes=['subtitle','small']))
        body.append(sidebar)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, hexpand=True, margin_top=24, margin_bottom=20, margin_start=30, margin_end=30)
        body.append(main)
        self.heading = Gtk.Label(xalign=0, css_classes=['page-title'])
        titlebar = Gtk.Box(spacing=12)
        self.heading.set_hexpand(True)
        titlebar.append(self.heading)
        self.spinner = Gtk.Spinner()
        self.home_button = Gtk.Button(label='← Discover', tooltip_text='Back to Discover home', visible=False, css_classes=['flat'])
        self.home_button.connect('clicked', lambda b: self.navigate('Discover'))
        titlebar.append(self.home_button)
        titlebar.append(self.spinner)
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Reload current view', css_classes=['flat'])
        refresh.connect('clicked', lambda b: self.reload_view())
        titlebar.append(refresh)
        self.tray_button = Gtk.Button(label='Dock',tooltip_text='Hide in the tray when supported; otherwise minimize to the dock/taskbar',css_classes=['flat'])
        self.tray_button.connect('clicked',lambda b:self.minimize_window(prefer_tray=True))
        titlebar.append(self.tray_button)
        main.append(titlebar)
        self.search = Gtk.SearchEntry(placeholder_text='Search apps or describe a task, e.g. edit photos…', hexpand=True)
        self.search.connect('activate', self.search_packages)
        main.append(self.search)
        self.hero = Gtk.Box(spacing=24, css_classes=['hero'])
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True)
        intro.append(Gtk.Label(label='APPS & UPDATES', xalign=0, css_classes=['eyebrow']))
        intro.append(Gtk.Label(label='Find your next favorite.', xalign=0, wrap=True, css_classes=['hero-title']))
        intro.append(Gtk.Label(label='Create something. Learn something. Make your desktop yours.', wrap=True, xalign=0, css_classes=['subtitle']))
        self.home_update_label=Gtk.Label(label='Update status has not been checked yet.',xalign=0,wrap=True,css_classes=['subtitle'])
        intro.append(self.home_update_label)
        explore = Gtk.Button(label='Review app updates', halign=Gtk.Align.START, css_classes=['pill'], margin_top=6)
        explore.connect('clicked',self.queue_all_app_updates)
        quicklinks = Gtk.Box(spacing=8)
        quicklinks.append(explore)
        check_now=Gtk.Button(label='Check now',css_classes=['flat'])
        check_now.connect('clicked',lambda b:self.check_updates(True))
        quicklinks.append(check_now)
        welcome = Gtk.Button(label='Coming from Windows?', valign=Gtk.Align.END, css_classes=['flat'])
        welcome.connect('clicked', lambda b: self.navigate('Getting started'))
        quicklinks.append(welcome)
        intro.append(quicklinks)
        self.hero.append(intro)
        artwork = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        artwork.append(app_icon('gimp', 80))
        artwork.append(app_icon('krita', 64))
        self.hero.append(artwork)
        self.description = Gtk.Label(xalign=0, wrap=True, css_classes=['subtitle'])
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=['boxed-list'])
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        self.build_discover()
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.content.append(self.hero)
        self.content.append(self.description)
        self.content.append(self.home)
        self.content.append(self.list)
        scroll.set_child(self.content)
        self.scroll = scroll
        main.append(scroll)
        self.activity = Gtk.Box(spacing=10, css_classes=['setup-banner'], visible=False)
        self.activity_icons = Gtk.Box(spacing=8)
        self.activity.append(self.activity_icons)
        self.activity_label = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.activity.append(self.activity_label)
        self.activity_progress = Gtk.ProgressBar(width_request=110, valign=Gtk.Align.CENTER, show_text=True)
        self.activity.append(self.activity_progress)
        main.append(self.activity)
        footer = Gtk.Box(spacing=12)
        self.status = Gtk.Label(label='Ready', xalign=0, hexpand=True, wrap=True, css_classes=['subtitle','small'])
        footer.append(self.status)
        self.review = Gtk.Button(label='Review queue', css_classes=['suggested-action'])
        self.review.connect('clicked', lambda b: self.navigate('Queue'))
        footer.append(self.review)
        main.append(footer)
        self.win.set_content(outer)
        for name, callback, accelerators in [
            ('search', lambda action, parameter: self.focus_search(), ['<Primary>f']),
            ('discover', lambda action, parameter: self.navigate('Discover'), ['<Alt>Left']),
            ('open-updates', lambda action, parameter: self.open_updates(), []),
            ('open-flatpaks', lambda action, parameter: (self.win.present(), self.navigate('Flatpak apps', 'updates')), []),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)
            self.set_accels_for_action('app.' + name, accelerators)
        self.tray = Tray(APP_ID, self.open_updates, lambda: self.check_updates(True), self.request_quit, self.tray_status_changed)
        self.win.connect('close-request', self.close_window)
        self.refresh_update_identity()
        self.navigate('Discover')
        self.win.present()
        surface=self.win.get_surface()
        if surface: surface.connect('notify::state',self.toplevel_state_changed)
        if not DEMO:
            GLib.idle_add(self.show_interrupted_operations)
            GLib.timeout_add_seconds(2,lambda:(self.check_requirements(False),False)[1])
            if self.appearance['check_on_startup']: GLib.timeout_add_seconds(5, self.initial_update_check)
            self.configure_checks()
            if self.launch_background and self.appearance['start_minimized']:
                GLib.timeout_add(700, lambda: (self.minimize_window(), False)[1])

    def show_interrupted_operations(self):
        pending = [(name, journal) for name, journal in self.operation_journals.items() if journal.pending()]
        if not pending: return False
        dialog = Adw.MessageDialog(transient_for=self.win, heading='Check previous changes', body='A previous operation may have stopped or failed: ' + ', '.join(name for name, journal in pending) + '. Some changes may already have completed. Check Library and Updates, or scan Storage again, before retrying. Forge will not automatically repeat or roll back these changes.')
        dialog.add_response('ok', 'I will review the current state')
        dialog.set_close_response('ok')
        def acknowledged(dialog, response):
            for name, journal in pending:
                try: journal.acknowledge()
                except OSError: pass
        dialog.connect('response', acknowledged)
        dialog.present()
        return False

    def set_progress(self, percent):
        if hasattr(self, 'activity_progress'):
            if percent is None:
                self.activity_progress.pulse()
                self.activity_progress.set_text('Working…')
            else:
                self.activity_progress.set_fraction(percent / 100)
                self.activity_progress.set_text(f'{percent}%')

    def set_login_startup(self, widget):
        if getattr(widget, '_forge_resetting', False): return
        desired = widget.get_active()
        previous = self.appearance['launch_at_login']
        if DEMO:
            widget._forge_resetting = True
            widget.set_active(previous)
            widget._forge_resetting = False
            self.set_status('Demo mode: login startup is not changed.')
            return
        widget.set_sensitive(False)
        def finished(allowed, error):
            widget.set_sensitive(True)
            if error:
                widget._forge_resetting = True
                widget.set_active(previous)
                widget._forge_resetting = False
                self.message('Startup setting was not changed', error)
            else: self.change_appearance('launch_at_login', allowed)
        self.startup_manager.set(desired, self.appearance['start_minimized'], finished)

    def set_start_minimized(self, value):
        if DEMO or not self.appearance['launch_at_login']:
            self.change_appearance('start_minimized', value)
            return
        def finished(allowed, error):
            if error:
                self.message('Could not change login behavior', error)
                self.navigate('Appearance')
            else: self.change_appearance('start_minimized', value)
        self.startup_manager.set(True, value, finished)

    def flatpak_icon(self, app, size=36):
        identifier = app['id'].casefold()
        aliases = {'com.calibre_ebook.calibre':'calibre', 'org.mozilla.thunderbird':'thunderbird', 'org.mozilla.firefox':'firefox', 'org.videolan.vlc':'vlc', 'org.libreoffice.libreoffice':'libreoffice-writer'}
        name = aliases.get(identifier, app['id'])
        for root in APP_ICON_ROOTS:
            path = root / 'sources.json'
            try:
                records = json.loads(path.read_text())
                name = next((key for key,value in records.items() if (value.get('component') or '').removesuffix('.desktop').casefold() == identifier), name)
                break
            except (OSError, ValueError): continue
        return app_icon(name, size)

    def flatpak_page(self, mode='list', query=''):
        if self.locked or self.flatpaks.busy: return
        self.flatpak_mode = mode
        self.clear()
        self.heading.set_text({'list':'Your Flatpak apps','updates':'Flatpak updates','search':'Find Flatpak apps','sources':'Flatpak sources'}[mode])
        self.description.set_text('Flatpak apps are separate from system packages. “Just me” and “All users” refer to different installations.')
        row = self.note('Flatpak apps', 'Search above, or choose a view. App installation and updates always ask for confirmation.')
        for label, view in [('Installed','list'),('Updates','updates'),('Sources','sources')]:
            button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda b,v=view:self.flatpak_page(v))
            row.add_suffix(button)
        if mode == 'sources':
            row = self.note('Add Flathub for my account', 'Optional app source: https://dl.flathub.org/repo/flathub.flatpakrepo. Existing sources are not replaced.')
            button = Gtk.Button(label='Add Flathub', valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda b:self.confirm_flatpak('add-flathub','user'))
            row.add_suffix(button)
            def load_scope(scope):
                def loaded(text,error):
                    if error:self.note('Could not read ' + scope + ' sources',error)
                    else:
                        for line in text.splitlines():
                            fields=line.split('\t')
                            if len(fields)>=3:self.note(fields[1] or fields[0], fields[0] + ' · ' + ('Just me' if scope=='user' else 'All users') + '\n' + fields[2])
                    if scope=='user':load_scope('system')
                    else:self.busy_ui(False)
                self.flatpaks.run('sources',scope,loaded)
            if not DEMO:
                self.busy_ui(True)
                load_scope('user')
            return
        if mode == 'updates':
            row=self.note('All app updates','Gather updates for your account and all users into Downloads in one step.')
            easy=Gtk.Button(label='Review all app updates',valign=Gtk.Align.CENTER,css_classes=['suggested-action'])
            easy.connect('clicked',self.queue_all_app_updates);row.add_suffix(easy)
            row = self.note('Update one installation', 'Add available app and runtime updates to Downloads for the selected installation. Nothing is applied until you review and confirm.')
            for label, scope in [('Just me','user'),('All users','system')]:
                button=Gtk.Button(label=label,valign=Gtk.Align.CENTER)
                button.connect('clicked',lambda b,s=scope:self.queue_flatpak_updates(s))
                row.add_suffix(button)
        self.busy_ui(True)
        def loaded(apps, errors):
            self.busy_ui(False)
            if not apps:self.note('No apps to show', 'Try another search or add Flathub under Sources. Update lists can also be empty when no app updates are available.')
            seen=set()
            for app in apps:
                key=(app['scope'],app['id'],app['branch'],app['remote'],app['arch'])
                if key in seen:continue
                seen.add(key)
                scope_label='Just me' if app['scope']=='user' else 'All users'
                source_details=' · '.join(value for value in ['Flatpak runtime' if app.get('kind')=='runtime' else 'Flatpak',app['remote'] or 'Local bundle',scope_label,app['version']] if value)
                row=self.note('Forge' if app['id']==APP_ID else app['name'],app['summary']+'\n'+source_details)
                row.add_prefix(self.flatpak_icon(app))
                operation={'list':'remove','search':'install','updates':'update'}[mode]
                button=Gtk.Button(label='Queued' if operation=='update' and (app['scope'],app_ref(app)) in self.flatpak_queue else {'remove':'Remove','install':'Install','update':'Update'}[operation],valign=Gtk.Align.CENTER)
                button.connect('clicked',lambda b,a=app,o=operation:self.enqueue_flatpak_updates([a]) if o=='update' else self.confirm_flatpak(o,a['scope'],a))
                row.add_suffix(button)
            for error in errors:self.note('A Flatpak source could not be read',error)
            self.set_status(f'{len(seen)} Flatpak app entries · scopes are shown separately')
        if DEMO:
            loaded([{'id':'org.gimp.GIMP','name':'GIMP','summary':'Image editor (sample)','version':'demo','branch':'stable','remote':'flathub','arch':'x86_64','scope':'user'}],[])
        else:self.flatpaks.both(mode,loaded,query=query)

    def confirm_flatpak(self, operation, scope, app=None):
        if self.locked or self.flatpaks.busy or self.backend.busy:return
        if DEMO:
            self.set_status('Demo mode: Flatpak changes are disabled.')
            return
        if operation=='remove' and app and app['id']==APP_ID:
            self.message('Remove Forge with your software installer','Forge will not uninstall itself while it is running.')
            return
        self.locked=True
        scope_label='your account' if scope=='user' else 'all users on this computer'
        title={'install':'Install Flatpak app?','remove':'Remove Flatpak app?','update':'Update Flatpak app?','update-all':'Update this Flatpak installation?','add-flathub':'Add Flathub?'}[operation]
        if app and app.get('kind')=='runtime': title='Update shared Flatpak component?'
        name=app['name'] if app else 'All Flatpak apps and runtimes' if operation=='update-all' else 'Flathub'
        body=name+'\n\nInstallation: '+scope_label+'. '
        if app:body+='Source: '+app['remote']+'. App ID: '+app['id']+'. Branch: '+app['branch']+'.\n\n'
        body += 'Flatpak resolves required runtimes and related components during this operation. This is a selection confirmation, not a complete dependency simulation. '
        body += 'App data is kept when removing an app. ' if operation=='remove' else ''
        body += 'System-wide changes may need administrator authentication. Nothing is changed until you continue.'
        def show(metadata='', error=None):
            if error:
                self.locked=False
                self.message('Could not read app permissions',error)
                return
            dialog=Adw.MessageDialog(transient_for=self.win,heading=title,body=body)
            dialog.add_response('cancel','Cancel');dialog.add_response('apply',{'add-flathub':'Add source','remove':'Remove','install':'Install'}.get(operation,'Update'))
            dialog.set_default_response('cancel');dialog.set_close_response('cancel')
            dialog.set_response_appearance('apply',Adw.ResponseAppearance.DESTRUCTIVE if operation=='remove' else Adw.ResponseAppearance.SUGGESTED)
            if metadata:
                label=Gtk.Label(label='Requested access (publisher metadata):\n'+permissions_summary(metadata)+'\n\nTechnical details:\n'+metadata,xalign=0,selectable=True,wrap=True)
                scroll=Gtk.ScrolledWindow(min_content_height=100,max_content_height=220,propagate_natural_height=True)
                scroll.set_child(label);dialog.set_extra_child(scroll)
            def answered(d,response):
                if response!='apply':self.locked=False;return
                self.busy_ui(True)
                self.transaction_activity([],True)
                self.activity_label.set_text('Working with Flatpak…')
                self.activity_progress.set_text('Working…')
                self.activity_progress.pulse()
                if app:self.activity_icons.append(self.flatpak_icon(app,36))
                def finished(text,error):
                    self.locked=False;self.busy_ui(False);self.transaction_activity([],False)
                    if error:self.message('Flatpak operation did not complete',error+'\n\nRecheck the installed/update lists before retrying. Some steps may already have completed.')
                    else:
                        self.set_status('Flatpak operation completed.')
                        self.flatpak_page('sources' if operation=='add-flathub' else 'list')
                    self.check_updates()
                self.flatpaks.run(operation,scope,finished,app=app)
            dialog.connect('response',answered);dialog.present()
        if operation=='install':self.flatpaks.run('inspect',scope,show,app=app)
        else:show()

    def reload_view(self):
        if self.page == 'Flatpak apps': self.flatpak_page(getattr(self, 'flatpak_mode', 'list'), self.search.get_text())
        elif self.page == 'Updates': self.check_updates(True)
        else: self.navigate(self.page)

    def request_quit(self):
        if self.locked and (self.backend.busy or self.flatpaks.busy or self.cleaner.busy or self.requirements.busy):
            self.win.present()
            self.set_status('Package changes are still running. Wait for the system to finish before quitting Forge.')
            return
        self.quit()

    def close_window(self, window):
        if self.locked and (self.backend.busy or self.flatpaks.busy or self.cleaner.busy or self.requirements.busy):
            self.set_status('Package changes are still running. Keep Forge open until they finish.')
            return True
        if self.appearance['close_action'] != 'quit':
            self.minimize_window()
            return True
        return False

    def check_requirements(self,requested=True):
        if DEMO or self.requirements.busy or self.locked:return
        def checked(missing,issues,details):
            panel_missing='GNOME' in os.environ.get('XDG_CURRENT_DESKTOP','').upper() and not self.tray.available
            if not missing and not issues and not panel_missing:
                if requested:self.message('Required components are ready','\n'.join(details)+('\nDesktop panel support available' if self.tray.available else ''))
                return
            labels={'packagekit':'System package service (PackageKit)','python':'Host Python for artwork and storage','flatpak':'Flatpak app support'}
            body='\n'.join(labels[key] for key in missing)
            if issues:body+='\n\n'+'\n'.join(issues)
            if panel_missing:body+='\n\nGNOME panel icon support is missing. Enable it to keep Forge in the top panel.'
            dialog=Adw.MessageDialog(transient_for=self.win,heading='Finish setting up Forge',body=body+'\n\nInstall missing components before using the affected features. Your system will request administrator authentication.')
            dialog.add_response('cancel','Later')
            if missing and self.host['family'] in ('fedora','ubuntu','debian','arch'):dialog.add_response('install','Install required components')
            if panel_missing:dialog.add_response('panel','Set up panel icon')
            dialog.set_default_response('cancel');dialog.set_close_response('cancel')
            def answered(d,response):
                if response=='panel':self.open_tray_setup();return
                if response!='install':return
                self.locked=True;self.busy_ui(True)
                def installed(out,error):
                    self.locked=False;self.busy_ui(False)
                    if error:self.message('Setup did not complete',error)
                    else:self.check_requirements(True)
                self.requirements.install(self.host['family'],missing,installed)
            dialog.connect('response',answered);dialog.present()
        self.requirements.check(checked)

    def open_tray_setup(self):
        if DEMO:return
        if self.tray.available:
            self.message('Panel support is ready','Forge is registered with the desktop tray. Use Tray to hide the window and open Forge from its panel icon.');return
        dialog=Adw.MessageDialog(transient_for=self.win,heading='Enable the GNOME panel icon',body='Forge needs AppIndicator and KStatusNotifierItem Support to show its icon in the GNOME panel. Install the compatible extension from GNOME’s extension service. GNOME may ask you to confirm; Forge will reconnect when it is ready.')
        dialog.add_response('cancel','Cancel');dialog.add_response('install','Install panel support');dialog.set_close_response('cancel')
        def answered(d,response):
            if response!='install':return
            args=['gdbus','call','--session','--dest','org.gnome.Shell.Extensions','--object-path','/org/gnome/Shell/Extensions','--method','org.gnome.Shell.Extensions.InstallRemoteExtension','appindicatorsupport@rgcjonas.gmail.com']
            def finished(out,error):
                self.tray.register()
                if error:self.message('Check panel support','GNOME could not confirm installation. Open Extension Manager and check AppIndicator support. You may need to sign out and back in.\n\n'+error)
                else:self.set_status('Panel support installed. Forge is reconnecting to the desktop tray.')
            self.requirements.command(args,finished)
        dialog.connect('response',answered);dialog.present()

    def tray_status_changed(self):
        if not hasattr(self,'tray'):return
        if hasattr(self,'tray_button'):
            self.tray_button.set_label('Tray' if self.tray.available else 'Dock')
            self.tray_button.set_tooltip_text(self.tray.reason)
        if hasattr(self,'tray_status_row'):self.tray_status_row.set_subtitle(self.tray.reason)
        if not self.tray.available and self.background_hold:
            self.win.present();self.win.minimize()
            self.release();self.background_hold=False
            self.set_status('Tray support disappeared. Forge is available in the dock/taskbar.')

    def toplevel_state_changed(self,surface,pspec):
        if self.appearance['close_action']=='tray' and self.tray.available and surface.get_state() & Gdk.ToplevelState.MINIMIZED:
            self.minimize_window(prefer_tray=True)

    def minimize_window(self,prefer_tray=False):
        wants_tray = prefer_tray or self.appearance['close_action']=='tray'
        if wants_tray and self.tray.available:
            if not self.background_hold:
                self.hold();self.background_hold=True
            self.win.set_visible(False)
        else:
            if wants_tray:self.set_status('No desktop tray host is active. Using the dock/taskbar; tray setup is available in Settings.')
            self.win.minimize()

    def configure_checks(self):
        if self.check_timer:
            GLib.source_remove(self.check_timer)
            self.check_timer = None
        if not DEMO and self.appearance['check_interval']:
            self.check_timer = GLib.timeout_add_seconds(self.appearance['check_interval'] * 60, self.periodic_update_check)

    def open_updates(self):
        self.win.present()
        self.navigate('Updates')

    def initial_update_check(self):
        if self.backend.busy or self.locked:
            return True
        self.check_updates(refresh=True)
        return False

    def periodic_update_check(self):
        self.check_updates()
        return True

    def refresh_update_identity(self):
        count = combined_update_count(self.update_state.count, self.flatpak_update_state.count)
        self.update_badge.set_label(str(count or ''))
        self.update_badge.set_visible(bool(count))
        self.update_nav_icon.set_from_icon_name('software-update-available-symbolic' if count else 'emblem-ok-symbolic' if count == 0 else 'view-refresh-symbolic')
        self.win.set_icon_name(APP_ID + ('.Updates' if count else ''))
        if hasattr(self, 'tray'): self.tray.update(count)
        if count == 0: self.withdraw_notification('system-updates')
        if hasattr(self,'home_update_label'):
            app_count=self.flatpak_update_state.count;native_count=self.update_state.count
            self.home_update_label.set_text('Apps & runtimes: '+(str(app_count)+' updates' if app_count is not None else 'not checked')+' · System packages: '+(str(native_count)+' updates' if native_count is not None else 'not checked'))

    def check_updates(self, requested=False, refresh=False):
        if DEMO:
            if requested: self.set_status('Demo mode: live update checks are disabled.')
            return
        if self.monitor_backend.busy or self.flatpak_monitor.busy or self.backend.busy or self.flatpaks.busy or self.locked:
            if requested: self.set_status('An operation is running. Check for updates again when it finishes.')
            return
        if requested: self.set_status('Checking system packages and Flatpak apps…')
        def flatpak_checked(apps, errors):
            sample = [('Package', (2, app['scope'] + '|' + app_ref(app), '')) for app in apps]
            changed = self.flatpak_update_state.accept(sample, '\n'.join(errors) if errors else None)
            self.refresh_update_identity()
            if changed and self.appearance['update_notifications']:
                note = Gio.Notification.new('Flatpak updates are available')
                note.set_body(f'{self.flatpak_update_state.count} Flatpak app/runtime updates are ready to review.')
                note.set_icon(Gio.ThemedIcon.new(APP_ID + '.Updates'))
                note.set_default_action('app.open-flatpaks')
                self.send_notification('flatpak-updates', note)
            elif self.flatpak_update_state.count == 0: self.withdraw_notification('flatpak-updates')
        self.flatpak_monitor.both('updates', flatpak_checked)
        def checked(results, error):
            should_notify = self.update_state.accept(results, error)
            if error:
                if requested: self.message('Could not check for updates', error)
                return
            self.last_checked = GLib.DateTime.new_now_local().format('%Y-%m-%d %H:%M')
            self.refresh_update_identity()
            if requested:
                if self.page == 'Updates' and not self.backend.busy and not self.locked:
                    self.load('GetUpdates', GLib.Variant('(t)', (0,)))
                self.set_status(f'{self.update_state.count} updates reported by the host’s current package metadata.')
            if should_notify and self.appearance['update_notifications']:
                note = Gio.Notification.new('Updates are available')
                note.set_body(f'{self.update_state.count} system package updates are ready to review. Forge will not install them automatically.')
                note.set_icon(Gio.ThemedIcon.new(APP_ID + '.Updates'))
                note.set_default_action('app.open-updates')
                self.send_notification('system-updates', note)
            elif self.update_state.count == 0:
                self.withdraw_notification('system-updates')
        def refreshed(results, error):
            if error: checked([], error)
            else: self.monitor_backend.run('GetUpdates', GLib.Variant('(t)', (0,)), checked)
        if requested or refresh:
            self.monitor_backend.run('RefreshCache', GLib.Variant('(b)', (False,)), refreshed, interactive=bool(requested))
        else:
            self.monitor_backend.run('GetUpdates', GLib.Variant('(t)', (0,)), checked)

    def queue_all_updates(self, button=None):
        if self.locked or self.backend.busy or self.flatpaks.busy: return
        if self.queue and set(self.queue.values()) != {'UpdatePackages'}:
            self.message('Finish your current changes first', 'Review or clear your install/remove queue before adding all updates.')
            return
        self.busy_ui(True)
        self.set_status('Gathering system and Flatpak updates for Downloads…')
        def native_loaded(results,error):
            if error:
                self.busy_ui(False);self.message('Could not gather system updates',error);return
            ids=list(dict.fromkeys(values[1] for kind,values in results if kind=='Package'))
            def apps_loaded(apps,errors):
                self.busy_ui(False)
                if errors:
                    self.message('Could not gather every update','\n'.join(errors)+'\n\nNo new selections were added.');return
                self.available_updates=ids
                for pid in ids:self.queue[pid]='UpdatePackages'
                self.enqueue_flatpak_updates(apps)
                self.set_status(f'{len(ids)} system packages and {len(apps)} Flatpak updates added to Downloads. Review and apply each group below.')
            self.flatpaks.both('updates',apps_loaded)
        if DEMO:
            for pid in self.available_updates:self.queue[pid]='UpdatePackages'
            self.enqueue_flatpak_updates([{'id':'org.gimp.GIMP','name':'GIMP','scope':'user','kind':'app','arch':'x86_64','branch':'stable'}])
            self.busy_ui(False)
        else:self.backend.run('GetUpdates',GLib.Variant('(t)',(0,)),native_loaded)

    def set_status(self, text):
        self.status.set_text(text)
        if hasattr(self, 'activity') and self.activity.get_visible():
            self.activity_label.set_text(text)

    def transaction_activity(self, ids, visible):
        while self.activity_icons.get_first_child():
            self.activity_icons.remove(self.activity_icons.get_first_child())
        seen = set()
        for pid in ids:
            name = package_parts(pid)[0]
            if name not in seen and len(seen) < 4:
                self.activity_icons.append(app_icon(name, 36))
                seen.add(name)
        self.activity_progress.set_fraction(0)
        self.activity_progress.set_text('Preparing…')
        self.activity_label.set_text('Preparing package changes…')
        self.activity.set_visible(visible)

    def busy_ui(self, busy):
        self.spinner.set_spinning(busy)
        self.search.set_sensitive(not busy)
        for button in self.nav.values(): button.set_sensitive(not busy)

    def refresh_appearance(self):
        manager = Adw.StyleManager.get_default()
        self.appearance_provider.load_from_data(appearance_css(self.appearance, manager.get_dark()).encode())

    def apply_appearance(self):
        manager = Adw.StyleManager.get_default()
        manager.set_color_scheme({'system': Adw.ColorScheme.DEFAULT, 'light': Adw.ColorScheme.FORCE_LIGHT, 'dark': Adw.ColorScheme.FORCE_DARK}[self.appearance['scheme']])
        self.refresh_appearance()

    def change_appearance(self, key, value):
        self.appearance = clean_appearance({**self.appearance, key: value})
        self.apply_appearance()
        if key == 'check_interval': self.configure_checks()
        if self.appearance['close_action'] != 'tray' and self.background_hold:
            self.release()
            self.background_hold = False
        if not self.appearance['update_notifications']:
            self.withdraw_notification('system-updates')
            self.withdraw_notification('flatpak-updates')
        try:
            self.appearance_store.save(self.appearance)
            self.set_status('Preferences saved · applies only to Forge')
        except OSError as error:
            self.message('Appearance applied for this session', 'Could not save preferences: ' + str(error))

    def show_appearance(self):
        self.note('Forge '+VERSION,'Apps, system packages, and updates · '+self.host['family'].title())
        row=self.note('Required components','Check the system package service, host Flatpak, and host Python. Install anything missing through normal system authorization.')
        setup=Gtk.Button(label='Check setup',valign=Gtk.Align.CENTER)
        setup.connect('clicked',lambda b:self.check_requirements(True));row.add_suffix(setup)
        for key, title, subtitle, choices in [
            ('scheme', 'Color scheme', 'Use a light or dark interface, or follow your desktop preference.', SCHEMES),
            ('accent', 'Accent color', 'Highlight navigation, buttons, and cards with your favorite color.', ACCENTS),
        ]:
            row = Adw.ComboRow(title=title, subtitle=subtitle, model=Gtk.StringList.new([label for value, label in choices]))
            row.set_selected([value for value, label in choices].index(self.appearance[key]))
            row.connect('notify::selected', lambda r, pspec, k=key, options=choices: self.change_appearance(k, options[r.get_selected()][0]))
            self.list.append(row)
        row = self.note('Compact layout', 'Fit more package rows and cards on screen.')
        switch = Gtk.Switch(active=self.appearance['compact'], valign=Gtk.Align.CENTER)
        switch.connect('notify::active', lambda w, pspec: self.change_appearance('compact', w.get_active()))
        row.add_suffix(switch)
        row.set_activatable_widget(switch)
        row = self.note('Show technical package details', 'Include package names, versions, and processor architecture in app lists. Leave off for a simpler view.')
        details = Gtk.Switch(active=self.appearance['technical_details'], valign=Gtk.Align.CENTER)
        details.connect('notify::active', lambda w, pspec: self.change_appearance('technical_details', w.get_active()))
        row.add_suffix(details)
        row.set_activatable_widget(details)
        for key, title, description in [
            ('update_notifications', 'Notify me about updates', 'Show a desktop notification when the available system update list changes. Nothing is installed automatically.'),
            ('check_on_startup', 'Check updates when Forge starts', 'Check system packages and Flatpak apps after you open Forge or sign in with startup enabled.'),
        ]:
            row = self.note(title, description)
            toggle = Gtk.Switch(active=self.appearance[key], valign=Gtk.Align.CENTER)
            toggle.connect('notify::active', lambda w, pspec, k=key: self.change_appearance(k, w.get_active()))
            row.add_suffix(toggle)
            row.set_activatable_widget(toggle)
        self.note('STARTUP & BACKGROUND', 'Login startup uses your desktop’s permission system. Checks notify you; they never install updates automatically.').add_css_class('section')
        for key, title, choices in [
            ('check_interval', 'Check for updates', [(0,'No scheduled checks'),(15,'Every 15 minutes'),(30,'Every 30 minutes'),(60,'Every hour'),(240,'Every 4 hours'),(1440,'Daily')]),
            ('close_action', 'When I close the window', [('quit','Quit Forge'),('minimize','Minimize to dock / taskbar'),('tray','Hide in tray (dock fallback)')]),
        ]:
            row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for value,label in choices]))
            row.set_selected([value for value,label in choices].index(self.appearance[key]))
            row.connect('notify::selected', lambda r,p,k=key,c=choices:self.change_appearance(k,c[r.get_selected()][0]))
            self.list.append(row)
        self.tray_status_row=self.note('Desktop tray status',self.tray.reason)
        setup=Gtk.Button(label='GNOME tray setup',valign=Gtk.Align.CENTER)
        setup.connect('clicked',lambda b:self.open_tray_setup())
        setup.set_visible('GNOME' in os.environ.get('XDG_CURRENT_DESKTOP','').upper())
        self.tray_status_row.add_suffix(setup)
        retry=Gtk.Button(label='Retry',valign=Gtk.Align.CENTER)
        retry.connect('clicked',lambda b:self.tray.register());self.tray_status_row.add_suffix(retry)
        row = self.note('Launch Forge when I sign in', 'Your desktop may ask permission. Startup is per user, after login—not a system boot service.')
        login = Gtk.Switch(active=self.appearance['launch_at_login'], valign=Gtk.Align.CENTER)
        login.connect('notify::active', lambda w,p:self.set_login_startup(w))
        row.add_suffix(login)
        row.set_activatable_widget(login)
        row = self.note('Start minimized at login', 'Start in the tray when supported and selected; otherwise use the dock/taskbar.')
        minimized = Gtk.Switch(active=self.appearance['start_minimized'], valign=Gtk.Align.CENTER)
        minimized.connect('notify::active', lambda w,p:self.set_start_minimized(w.get_active()))
        row.add_suffix(minimized)
        row.set_activatable_widget(minimized)
        self.note('Last system check', self.last_checked)
        row = self.note('Your style, throughout Forge', 'The current theme applies to Discover, package lists, and confirmation dialogs. Following system appearance depends on your desktop exposing its preference.')
        row.add_prefix(Gtk.Image(icon_name='preferences-desktop-theme-symbolic', pixel_size=32, css_classes=['repo-icon']))
        row = self.note('Restore Forge defaults', 'Dark mode, Forge indigo, and comfortable spacing.')
        reset = Gtk.Button(label='Reset appearance', valign=Gtk.Align.CENTER)
        def defaults(button):
            keep = {k:self.appearance[k] for k in ('update_notifications','tray_background','launch_at_login','start_minimized','check_on_startup','check_interval','close_action')}
            self.appearance = {**APPEARANCE_DEFAULTS, **keep}
            self.apply_appearance()
            try: self.appearance_store.save(self.appearance)
            except OSError as error:
                self.message('Could not save defaults', str(error))
                return
            self.navigate('Appearance')
            self.set_status('Default appearance restored')
        reset.connect('clicked', defaults)
        row.add_suffix(reset)
        self.set_status('Preferences · no administrator access needed')

    def open_link(self, url):
        try: Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error as error: self.message('Could not open browser', error.message)

    def finish_setup(self, *args):
        if self.locked or self.backend.busy: return
        if not DEMO:
            try: self.setup_state.save()
            except OSError as error:
                self.message('Could not save setup preference', str(error))
                return
        self.navigate('Discover')


    def clear(self):
        while self.list.get_first_child(): self.list.remove(self.list.get_first_child())

    def note(self, title, subtitle=''):
        row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle))
        self.list.append(row)
        return row

    def navigate(self, page, flatpak_view='list'):
        if page != 'Queue' and (self.backend.busy or self.flatpaks.busy or self.cleaner.busy or self.locked):
            self.set_status('Please wait for the current operation to finish.')
            return
        self.page = page
        self.generation += 1
        for p, b in self.nav.items():
            (b.add_css_class if p == page else b.remove_css_class)('active')
        self.heading.set_text({'Discover': 'Discover', 'Installed': 'Your library', 'Queue': 'Downloads & changes', 'Repositories': 'Software sources', 'Appearance': 'Settings'}.get(page, page))
        self.hero.set_visible(page == 'Discover')
        self.home.set_visible(page == 'Discover')
        self.home_button.set_visible(False)
        self.list.set_visible(page != 'Discover')
        self.scroll.get_vadjustment().set_value(0)
        self.search.set_visible(page in ('Discover','Installed','Flatpak apps'))
        self.clear()
        self.description.set_text({'Discover':'Find tools for what you want to do. Browse interests or describe a task in the search box.', 'Installed':'Packages currently installed on this system. Search to narrow the list.', 'Updates':'Available package updates. Add updates to your queue to review them.', 'Repositories':'Choose your software sources. Third-party repositories are optional and managed on your host system.', 'Queue':'Review your selections. Forge resolves the transaction before asking you to apply it.', 'Storage':'Review disk usage and selected cleanup categories. Nothing is deleted during a scan.', 'Flatpak apps':'Browse, install, and update Flatpak apps from your configured sources.', 'Getting started':'Familiar tasks, a few new ideas, and clear steps for getting started.', 'Appearance':'Make Forge feel at home. Changes apply immediately and are remembered for next time.'}[page])
        if page == 'Storage': self.storage_page()
        elif page == 'Flatpak apps': self.flatpak_page(flatpak_view, self.search.get_text() if flatpak_view == 'search' else '')
        elif page == 'Getting started': self.show_windows_guide()
        elif page == 'Appearance': self.show_appearance()
        elif page == 'Queue': self.show_queue()
        elif page == 'Installed': self.load('GetPackages', GLib.Variant('(t)', (4,)))
        elif page == 'Updates': self.load('GetUpdates', GLib.Variant('(t)', (0,)))
        elif page == 'Repositories': self.load('GetRepoList', GLib.Variant('(t)', (0,)))
        else:
            self.search.set_text('')
            self.set_status(f'{len(DISCOVER_APPS)} app ideas · Ctrl+F to search · Alt+Left for Discover')
            self.refresh_artwork()

    def search_packages(self, *args):
        if self.locked or self.backend.busy: return
        query = self.search.get_text().strip()
        if not query:
            if self.page == 'Discover': self.navigate('Discover')
            return
        self.heading.set_text(f'Search: {query}')
        if self.page == 'Flatpak apps':
            self.flatpak_page('search', query)
        elif self.page == 'Discover':
            self.show_catalog_search(query)
        else:
            self.load('SearchNames', GLib.Variant('(tas)', (4, [query])))

    def load(self, method, args):
        self.home.set_visible(False)
        self.hero.set_visible(False)
        self.list.set_visible(True)
        self.home_button.set_visible(self.page in ('Discover', 'Getting started'))
        self.scroll.get_vadjustment().set_value(0)
        self.clear()
        self.note('Loading…', 'Reading package information from your system.')
        self.busy_ui(True)
        def loaded(results, error):
            self.busy_ui(False)
            self.clear()
            if error:
                self.note('Package service unavailable', error)
                self.set_status('Could not load package information.')
                return
            if method == 'GetRepoList':
                self.show_repositories(results)
                return
            if method == 'GetUpdates':
                self.available_updates = list(dict.fromkeys(v[1] for k,v in results if k == 'Package'))
                self.update_state.accept(results)
                self.refresh_update_identity()
                fp_count = self.flatpak_update_state.count
                row = self.note('Flatpak app updates', 'Not checked yet' if fp_count is None else f'{fp_count} app/runtime updates reported.')
                view_fp = Gtk.Button(label='Review app updates', valign=Gtk.Align.CENTER)
                view_fp.connect('clicked',self.queue_all_app_updates)
                row.add_suffix(view_fp)
                row = self.note('Keep your system current', 'Review all updates together. Nothing changes until you approve the plan. This list uses the host’s current package metadata.')
                if self.available_updates or fp_count is None or fp_count:
                    all_updates = Gtk.Button(label='Add all updates to Downloads', valign=Gtk.Align.CENTER, css_classes=['suggested-action'])
                    all_updates.connect('clicked', self.queue_all_updates)
                    row.add_suffix(all_updates)
                check = Gtk.Button(label='Check again', valign=Gtk.Align.CENTER)
                check.connect('clicked', lambda b: self.check_updates(True))
                row.add_suffix(check)
            count = 0
            seen = set()
            for kind, values in results:
                if kind == 'RepoDetail':
                    repo, description, enabled = values
                    row = self.note(description, repo)
                    row.add_suffix(Gtk.Label(label='Enabled' if enabled else 'Disabled', css_classes=['pill']))
                    count += 1
                elif kind == 'Package':
                    info, pid, summary = values
                    if pid in seen: continue
                    seen.add(pid)
                    self.package_row(pid, summary, info == 1)
                    count += 1
            if not count: self.note('Nothing to show', 'No matching packages were returned by your system.')
            if method == 'Resolve':
                found = {package_parts(v[1])[0] for k,v in results if k == 'Package'}
                missing = [name for name in args.unpack()[1] if name not in found]
                if missing and count:
                    self.note('Some packages are not available', ', '.join(missing) + ' · availability depends on your enabled repositories.')
            self.set_status(f'{count:,} results · {"Sample data" if DEMO else "Host PackageKit"}')
        if DEMO:
            samples = [('Package',(2,'git;2.50.0;x86_64;fedora','Fast, distributed version control')),('Package',(2,'gimp;3.0.4;x86_64;fedora','Create, retouch, and edit images')),('Package',(1,'htop;3.4.1;x86_64;installed','Interactive process viewer'))]
            if method == 'Resolve':
                samples = [('Package', (2, f'{name};demo;x86_64;sample-repository', DISCOVER_APPS[name][1])) for name in args.unpack()[1] if name in DISCOVER_APPS]
            elif method == 'GetRepoList': samples = [('RepoDetail',('fedora','Fedora — base packages',True)),('RepoDetail',('updates','Fedora — updates',True))]
            elif method in ('SearchNames', 'SearchDetails'): samples = [x for x in samples if args.unpack()[1][0].lower() in x[1][1].lower()]
            elif method == 'GetPackages': samples = [x for x in samples if x[1][0] == 1]
            elif method == 'GetUpdates': samples = samples[:1]
            loaded(samples, None)
        else: self.backend.run(method, args, loaded)

    def catalog_id(self,name):
        ids={'gimp':'org.gimp.GIMP','vlc':'org.videolan.VLC','inkscape':'org.inkscape.Inkscape','krita':'org.kde.krita','blender':'org.blender.Blender','firefox':'org.mozilla.firefox','thunderbird':'org.mozilla.thunderbird','libreoffice-writer':'org.libreoffice.LibreOffice','libreoffice-calc':'org.libreoffice.LibreOffice','libreoffice-impress':'org.libreoffice.LibreOffice'}
        if name in ids:return ids[name]
        for root in APP_ICON_ROOTS:
            try:
                item=json.loads((root/'sources.json').read_text()).get(name,{})
                return (item.get('component') or name).removesuffix('.desktop')
            except (OSError,ValueError):continue
        return name

    def catalog_icon(self,name,size=48):
        path=self.catalog.image(self.catalog_id(name),'icon')
        if path:
            try:
                image=Gtk.Image.new_from_paintable(Gdk.Texture.new_from_filename(str(path)));image.set_pixel_size(size);return image
            except GLib.Error:pass
        return app_icon(name,size)

    def refresh_artwork(self,force=False):
        if DEMO or self.catalog.busy:return
        if hasattr(self,'artwork_refresh'):
            self.artwork_refresh.set_sensitive(False);self.artwork_refresh.set_label('Refreshing…')
        def loaded(error):
            while self.home.get_first_child():self.home.remove(self.home.get_first_child())
            self.build_discover()
            if error and force:self.set_status('Artwork refresh was unavailable. Cached and bundled pictures are still available.')
            elif force:self.set_status('App catalog artwork refreshed. No apps were installed or updated.')
        self.catalog.refresh([self.catalog_id(name) for name in DISCOVER_APPS],[self.catalog_id(name) for name in FEATURED],loaded,force)

    def build_discover(self):
        def section(title, caption):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            box.append(Gtk.Label(label=title, xalign=0, css_classes=['section-title']))
            box.append(Gtk.Label(label=caption, xalign=0, wrap=True, css_classes=['subtitle', 'small']))
            self.home.append(box)

        def flow(minimum, maximum):
            grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                               min_children_per_line=minimum, max_children_per_line=maximum,
                               row_spacing=12, column_spacing=12)
            self.home.append(grid)
            return grid

        row=Gtk.Box(spacing=12)
        text=Gtk.Label(label='Publisher screenshots and artwork from your app catalog',xalign=0,wrap=True,hexpand=True,css_classes=['subtitle','small'])
        row.append(text)
        self.artwork_refresh=Gtk.Button(label='Refresh artwork',css_classes=['flat'])
        self.artwork_refresh.connect('clicked',lambda b:self.refresh_artwork(True))
        row.append(self.artwork_refresh);self.home.append(row)
        section('In the spotlight', 'Explore app ideas. Catalog screenshots show the Flathub edition when available.')
        featured = flow(3, 3)
        for name, color in zip(FEATURED, ['mint', 'peach', 'lavender']):
            title, summary, icon = DISCOVER_APPS[name]
            record=self.catalog.get(self.catalog_id(name))
            button = Gtk.Button(css_classes=['app-tile'], hexpand=True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=155)
            screenshot=self.catalog.image(self.catalog_id(name),'screenshot')
            if screenshot:
                try:
                    picture=Gtk.Picture.new_for_paintable(Gdk.Texture.new_from_filename(str(screenshot)))
                    picture.set_can_shrink(True);picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                    picture.set_size_request(-1,130);box.append(picture)
                    credits=Gtk.Button(label='Screenshot info',css_classes=['flat','small'])
                    credits.connect('clicked',lambda b,r=dict(record):self.message('Publisher screenshot',r.get('caption','Publisher screenshot')+'\n\nSource: '+r.get('image_url','Flathub app catalog')))
                    box.append(credits)
                except GLib.Error:pass
            image = self.catalog_icon(name, 48)
            image.set_halign(Gtk.Align.START)
            box.append(image)
            box.append(Gtk.Label(label=title, xalign=0, css_classes=['tile-title']))
            box.append(Gtk.Label(label=summary, xalign=0, wrap=True, max_width_chars=24, lines=3, css_classes=['tile-copy']))
            if record.get('version'):box.append(Gtk.Label(label='Flathub catalog · '+record['version'],xalign=0,wrap=True,css_classes=['subtitle','small']))
            box.append(Gtk.Label(label='Explore app  →', xalign=0, css_classes=['eyebrow'], margin_top=8))
            button.set_child(box)
            button.connect('clicked', lambda b, n=name: self.show_app_detail(n))
            featured.insert(button, -1)

        section('What would you like to do?', 'Try a task, an app name, or a familiar alternative. No package names needed.')
        goals = flow(1, 3)
        for label, query in [('Edit photos', 'edit photos'), ('Write documents', 'write document'), ('Read ebooks', 'read ebooks'), ('Record my screen', 'record screen'), ('Explore accessibility', 'accessibility'), ('Find games', 'games')]:
            button = Gtk.Button(label=label, css_classes=['pill'])
            button.connect('clicked', lambda b, q=query: (self.search.set_text(q), self.search_packages()))
            goals.insert(button, -1)
        section('Browse your interests', 'Small collections of tools, picked by what you want to do.')
        categories = flow(1, 3)
        for category, (icon, caption, names) in COLLECTIONS.items():
            button = Gtk.Button(css_classes=['category-tile'])
            box = Gtk.Box(spacing=12)
            box.append(Gtk.Image(icon_name=icon, pixel_size=26, css_classes=['repo-icon']))
            copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            copy.append(Gtk.Label(label=category, xalign=0, css_classes=['section']))
            copy.append(Gtk.Label(label=f'{len(names)} package ideas', xalign=0, css_classes=['subtitle', 'small']))
            box.append(copy)
            button.set_child(box)
            button.connect('clicked', lambda b, c=category: self.browse_collection(c))
            categories.insert(button, -1)

        section('Build a better everyday setup', 'Useful starting points for a fresh install.')
        essentials = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=['boxed-list'])
        for name in ['firefox', 'thunderbird', 'libreoffice-writer', 'keepassxc']:
            title, summary, icon = DISCOVER_APPS[name]
            row = Adw.ActionRow(title=title, subtitle=summary)
            row.add_prefix(app_icon(name, 32))
            button = Gtk.Button(label='View', valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda b, n=name: self.show_app_detail(n))
            row.add_suffix(button)
            essentials.append(row)
        self.home.append(essentials)
        strip = Gtk.Box(spacing=16, css_classes=['setup-banner'])
        copy = Gtk.Label(label='Looking for more? Your repositories determine which packages Forge can find.', xalign=0, wrap=True, hexpand=True, css_classes=['subtitle'])
        strip.append(copy)
        button = Gtk.Button(label='Software sources', valign=Gtk.Align.CENTER)
        button.connect('clicked', lambda b: self.navigate('Repositories'))
        strip.append(button)
        self.home.append(strip)
        self.home.append(Gtk.Label(label='Curated suggestions · open a package to check your repositories.', wrap=True, xalign=0, css_classes=['subtitle','small'], margin_bottom=12))

    def browse_collection(self, category):
        self.show_app_collection(collection_names(category), category + ' · ' + COLLECTIONS[category][1])

    def show_windows_guide(self):
        if not self.discovery_view('Coming from Windows?', 'Find familiar tools and learn how installing software works on your Linux desktop.'): return
        row = self.note('Your app store, with you in control', 'Browse an app, choose Find install options, and add it to Downloads. Review changes shows any extra software required. Nothing is installed until you confirm.')
        row.add_prefix(Gtk.Image(icon_name='software-install-symbolic', pixel_size=32, css_classes=['repo-icon']))
        self.note('FAMILIAR TASKS, LINUX ALTERNATIVES', 'These suggestions help you explore. They do not promise identical features or automatic file migration.').add_css_class('section')
        for familiar, purpose, names, caveat in WINDOWS_ALTERNATIVES:
            row = self.note(familiar, purpose + '\n' + ', '.join(DISCOVER_APPS[name][0] for name in names))
            row.add_prefix(app_icon(names[0], 40))
            button = Gtk.Button(label='Explore alternatives', valign=Gtk.Align.CENTER)
            def explore(button, apps=names, title=familiar, note=caveat):
                self.show_app_collection(apps, 'Alternatives for ' + title)
                self.description.set_text(note)
            button.connect('clicked', explore)
            row.add_suffix(button)
        self.note('A FEW THINGS THAT WORK DIFFERENTLY', 'Start with apps you recognize. Your Linux desktop already includes tools for everyday system tasks.').add_css_class('section')
        self.note('Software sources', 'A source is a place your system gets apps and updates, similar to a store catalog. Forge shows sources for your detected Linux distribution. Adding a source changes which software your system trusts and can install.')
        self.note('Administrator prompts', 'Forge runs as your normal user. Your system may ask for administrator authentication when applying changes. You do not need to open a terminal or run Forge as administrator.')
        self.note('Updates & removals', 'Updates can include apps and system components. The Library includes system packages as well as apps, so only remove items you recognize. Forge highlights risky changes, but does not provide automatic rollback.')
        self.note('Windows installers', 'Windows .exe and .msi installers are not native Linux packages. This version of Forge does not install Windows programs. Use the Linux alternatives above when they meet your needs.')
        self.note('Flatpak, in plain language', 'A Flatpak is a Linux app package designed to work across distributions. Forge itself is supplied as a Flatpak. Open Flatpak apps to search, install, remove, and update apps from configured Flatpak sources.')
        row = self.note('Make it comfortable', 'Choose light or dark mode, an accent color, and comfortable or compact spacing. Technical package details can stay hidden until you want them.')
        button = Gtk.Button(label='Appearance', valign=Gtk.Align.CENTER)
        button.connect('clicked', lambda b: self.navigate('Appearance'))
        row.add_suffix(button)
        self.set_status('New to Linux · explore first, review before installing')

    def focus_search(self):
        if self.backend.busy or self.locked: return
        if self.page not in ('Discover', 'Installed', 'Flatpak apps'): self.navigate('Discover')
        self.search.grab_focus()

    def discovery_view(self, title, description):
        if self.backend.busy or self.locked: return False
        self.heading.set_text(title)
        self.description.set_text(description)
        self.home.set_visible(False)
        self.hero.set_visible(False)
        self.list.set_visible(True)
        self.home_button.set_visible(True)
        self.scroll.get_vadjustment().set_value(0)
        self.clear()
        return True

    def app_idea_row(self, name):
        title, summary, icon = DISCOVER_APPS[name]
        row = self.note(title, summary)
        row.add_prefix(app_icon(name, 40))
        button = Gtk.Button(label='About app', tooltip_text='Learn about ' + title, valign=Gtk.Align.CENTER)
        button.connect('clicked', lambda b: self.show_app_detail(name))
        row.add_suffix(button)

    def show_app_collection(self, names, title):
        if not self.discovery_view(title, 'Explore these app ideas, then check your software sources for available packages.'): return
        for name in names: self.app_idea_row(name)
        self.set_status(f'{len(names)} app ideas · availability not checked yet')

    def show_catalog_search(self, query):
        matches = catalog_matches(query)
        if not self.discovery_view('Find apps: ' + query, 'App ideas and packages from your enabled system repositories.'): return
        for name in matches:self.app_idea_row(name)
        self.note('System packages','Searching your enabled repositories…')
        generation=self.generation
        self.busy_ui(True)
        def loaded(results,error):
            self.busy_ui(False)
            if generation!=self.generation:return
            if error:
                self.note('System package search unavailable',error)
                self.set_status('Could not search system packages. Check Software sources.');return
            packages={v[1]:v for k,v in results if k=='Package'}
            self.note('SYSTEM PACKAGE RESULTS',f'{len(packages)} packages found. Installed packages are labeled; changes go to Downloads.')
            for info,pid,summary in list(packages.values())[:200]:self.package_row(pid,summary,info==1)
            if not packages:self.note('No system packages matched','Try a shorter app or package name, or check your enabled Software sources.')
            if len(packages)>200:self.note('More results available','Showing the first 200 packages. Refine your search to narrow the list.')
            row=self.note('Also search Flatpak apps','Search your configured Flatpak sources for another edition.')
            button=Gtk.Button(label='Find Flatpak apps',valign=Gtk.Align.CENTER)
            button.connect('clicked',lambda b:self.navigate('Flatpak apps','search'));row.add_suffix(button)
            self.set_status(f'{len(matches)} app ideas · {len(packages)} system package results')
        if DEMO:loaded([('Package',(2,'gimp;demo;x86_64;sample','Image editor (sample)'))],None)
        else:self.backend.run('SearchDetails',GLib.Variant('(tas)',(0,[query])),loaded)

    def show_app_detail(self, name):
        title, summary, icon = DISCOVER_APPS[name]
        if not self.discovery_view(title, summary): return
        row = self.note('About ' + title, summary)
        row.add_prefix(app_icon(name, 64))
        categories = [category for category in COLLECTIONS if name in collection_names(category)]
        self.note('Explore under', ' · '.join(categories))
        self.note('Installation source', 'System package · ' + native_package_names([name], self.host['family'])[0] + '\nForge checks the enabled sources on your host. Versions, downloads, and availability depend on those sources.')
        if name in APP_NOTES: self.note('Before you choose', APP_NOTES[name])
        self.note('You stay in control', 'Checking availability makes no changes. Installation requires adding a package to your queue, reviewing the resolved plan, and confirming it.')
        row = self.note('Available on your system?', 'Look up the exact package name in your software sources.')
        button = Gtk.Button(label='Find install options', valign=Gtk.Align.CENTER, css_classes=['suggested-action'])
        button.connect('clicked', lambda b: self.browse_packages([name], title))
        row.add_suffix(button)
        row = self.note('Also look for a Flatpak', 'Search your configured Flatpak sources. Publisher, features, and permissions may differ between editions.')
        fp_button = Gtk.Button(label='Find Flatpak', valign=Gtk.Align.CENTER)
        fp_button.connect('clicked', lambda b: (self.search.set_text(title), self.navigate('Flatpak apps', 'search')))
        row.add_suffix(fp_button)
        self.set_status('App overview · availability not checked yet')

    def browse_packages(self, names, title):
        if self.backend.busy or self.locked: return
        self.heading.set_text(title)
        self.description.set_text('Packages available from your configured sources. Review a package before adding it to your queue.')
        self.search.set_text('')
        family = getattr(self, 'host', {}).get('family', 'other')
        self.load('Resolve', GLib.Variant('(tas)', (0, native_package_names(names, family))))

    def show_repositories(self, results):
        repos = {v[0]: (v[1], v[2]) for k, v in results if k == 'RepoDetail'}
        if DEMO or not self.setup_state.complete():
            row = self.note('Welcome to Forge', 'Start with your software sources. Add optional definitions below, or continue with your existing repositories.')
            row.add_css_class('setup-banner')
            button = Gtk.Button(label='Continue to packages', valign=Gtk.Align.CENTER, css_classes=['suggested-action'])
            button.connect('clicked', self.finish_setup)
            row.add_suffix(button)
        release = ' · '.join(part for part in [self.host.get('version', ''), self.host.get('codename', '')] if part)
        self.note('Detected host', self.host['name'] + (' · ' + release if release else '') + '\nRepository suggestions match this host. No source is added just by opening this page.')
        if self.host['family'] == 'fedora':
            row = self.note('Fedora third-party definitions', 'Install fedora-workstation-repositories from your current sources, then return here to enable individual sources. Availability depends on Fedora version.')
            button = Gtk.Button(label='Find setup package', valign=Gtk.Align.CENTER)
            button.connect('clicked', self.find_repo_package)
            row.add_suffix(button)
        self.note('CONFIGURED ON YOUR SYSTEM', f'{sum(bool(v[1]) for v in repos.values())} enabled · {len(repos)} total').add_css_class('section')
        for repo, (description, enabled) in sorted(repos.items()):
            row = self.note(description, repo + ' · ' + repository_state(repo, repos))
            row.add_prefix(Gtk.Image(icon_name='drive-harddisk-symbolic', css_classes=['repo-icon']))
            button = Gtk.Button(label='Disable' if enabled else 'Enable', valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda b, r=repo, e=enabled: self.change_repo(r, not e))
            row.add_suffix(button)
        self.note('SOURCES FOR YOUR DISTRIBUTION', 'These source groups match your host. Only configured repository entries above have enable/disable controls.').add_css_class('section')
        for title, description in distro_sources(self.host):
            self.note(title, description)
        for title, repo_id, description, url in (REPO_CATALOG if self.host['family'] == 'fedora' else []):
            row = self.note(title, description + '\n' + repository_state(repo_id, repos))
            button = Gtk.Button(label='Setup guide' if repo_id not in repos else 'About source', valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda b, u=url: self.open_link(u))
            row.add_suffix(button)
        self.set_status(f'{len(repos)} configured repositories · ' + ('Demo · changes disabled' if DEMO else 'Host PackageKit'))

    def find_repo_package(self, *args):
        if self.backend.busy or self.locked: return
        if DEMO:
            self.set_status('Demo mode: setup package installation is disabled.')
            return
        self.busy_ui(True)
        def found(results, error):
            self.busy_ui(False)
            if error:
                self.message('Cannot find repository setup package', error)
                return
            candidates = [(v[1], v[2], v[0] == 1) for k, v in results if k == 'Package'
                          and package_parts(v[1])[0] == 'fedora-workstation-repositories']
            if any(installed for pid, summary, installed in candidates):
                self.message('Definitions already installed', 'Enable the sources listed in Repositories. Use Reload to check for new definitions.')
                return
            if not candidates:
                self.message('Setup package unavailable', 'Your enabled sources do not provide fedora-workstation-repositories. This setup option requires a compatible Fedora host with Fedora base repositories enabled.')
                return
            self.clear()
            self.description.set_text('Choose a repository definition package to queue. Installation still requires dependency review and confirmation. Return to Repositories afterward to enable sources.')
            for pid, summary, installed in candidates: self.package_row(pid, summary, installed)
            self.set_status('Add the setup package to your queue, then review it.')
        self.backend.run('Resolve', GLib.Variant('(tas)', (0, ['fedora-workstation-repositories'])), found)

    def change_repo(self, repo, enabled):
        if self.backend.busy or self.locked: return
        if DEMO:
            self.set_status('Demo mode: repository changes are disabled.')
            return
        self.locked = True
        verb = 'Enable' if enabled else 'Disable'
        d = Adw.MessageDialog(transient_for=self.win, heading=f'{verb} repository?', body=f'{repo}\n\nThis changes the host system’s software sources. Enabling a source makes its packages available to system package managers. Administrator authentication may be required.')
        d.add_response('cancel', 'Cancel')
        d.add_response('apply', verb)
        d.set_close_response('cancel')
        d.set_default_response('cancel')
        d.set_response_appearance('apply', Adw.ResponseAppearance.SUGGESTED)
        def answer(dialog, response):
            if response != 'apply':
                self.locked = False
                return
            self.busy_ui(True)
            def changed(results, error):
                self.locked = False
                self.busy_ui(False)
                if error: self.message('Repository change failed', error)
                else: self.navigate('Repositories')
            self.backend.run('RepoEnable', GLib.Variant('(sb)', (repo, enabled)), changed)
        d.connect('response', answer)
        d.present()

    def package_row(self, pid, summary, installed):
        name, version, arch, repo = package_parts(pid)
        title, subtitle = package_presentation(name, version, arch, repo, summary, self.appearance['technical_details'])
        row = self.note(title, subtitle)
        row.add_prefix(app_icon(name, 32))
        if installed:
            row.add_suffix(Gtk.Label(label='Installed', css_classes=['pill']))
        action = 'UpdatePackages' if self.page == 'Updates' else 'RemovePackages' if installed else 'InstallPackages'
        button = Gtk.Button(label='Queued' if pid in self.queue else {'InstallPackages':'Install','RemovePackages':'Remove','UpdatePackages':'Update'}[action], valign=Gtk.Align.CENTER)
        button.connect('clicked', lambda b: self.toggle(pid, action, b))
        row.add_suffix(button)

    def toggle(self, pid, action, button):
        if self.locked or self.backend.busy: return
        if pid in self.queue:
            del self.queue[pid]
            button.set_label({'InstallPackages':'Install','RemovePackages':'Remove','UpdatePackages':'Update'}[action])
        else:
            if self.queue and action not in set(self.queue.values()):
                self.message('Finish your current queue first', 'Keep installs, updates, and removals in separate transactions so the dependency preview matches the changes being applied.')
                return
            self.queue[pid] = action
            button.set_label('Queued')
        self.refresh_queue_count()

    def storage_page(self):
        self.clear()
        self.storage_categories = set()
        row = self.note('Storage & cleanup', 'Scan first, select categories, then review. No automatic cleaning or speed-boost claims.')
        scan = Gtk.Button(label='Scan storage',valign=Gtk.Align.CENTER,css_classes=['suggested-action'])
        scan.connect('clicked',lambda b:self.scan_storage());row.add_suffix(scan)
        if not self.storage_scan:
            self.note('What Forge scans', 'Old app caches (7+ days), rotated app logs (30+ days), old user crash reports (30+ days), and your Trash. Downloads, documents, saved passwords, browser profiles, and app settings are not scanned for deletion.')
            self.note('System cleanup', 'Package caches use the distribution’s package tool. Old system journals use a 30-day retention rule. These actions request administrator authentication.')
            return
        data = self.storage_scan
        self.note('Available disk space',GLib.format_size(data['free'])+' available out of '+GLib.format_size(data['total'])+' on your home filesystem.')
        self.note('CHOOSE WHAT TO CLEAN','Nothing is preselected. Close affected apps before clearing their cache.').add_css_class('section')
        categories=[('app_cache','Application caches','Files not modified for at least 7 days. Apps may rebuild or download this data.'),('app_logs','Application logs','Only old rotated logs in user cache/state folders, at least 30 days old. Current logs are preserved.'),('crash_reports','Crash reports','User-owned crash dumps in cache/state folders, at least 30 days old. Useful diagnostic data may be lost.'),('trash','Trash','Permanently remove the scanned files already in your Trash. This cannot be undone.')]
        for key,title,description in categories:
            items=[item for item in data['items'] if item['category']==key]
            size=sum(item['size'] for item in items)
            row=self.note(title,f'{len(items)} entries · '+GLib.format_size(size)+'\n'+description)
            check=Gtk.CheckButton(sensitive=bool(items))
            check.connect('toggled',lambda b,k=key:self.storage_categories.add(k) if b.get_active() else self.storage_categories.discard(k))
            row.add_suffix(check);row.set_activatable_widget(check)
        row=self.note('Review selected cleanup','Only files in this scan are candidates. Files changed since scanning are skipped.')
        review=Gtk.Button(label='Review cleanup',valign=Gtk.Align.CENTER)
        review.connect('clicked',lambda b:self.review_storage_cleanup());row.add_suffix(review)
        self.note('SYSTEM MAINTENANCE','These are separate system-managed actions, not deletion of arbitrary system folders.').add_css_class('section')
        package_text=('At least ' if data['package_partial'] else '')+GLib.format_size(data['package_size'])+' of downloaded packages found. The manager decides what is removed; Arch keeps three cached versions.'
        row=self.note('Package caches',package_text+'\nDownloads may be needed again for reinstalls or downgrades.')
        button=Gtk.Button(label='Clean package cache',valign=Gtk.Align.CENTER,sensitive=data['system_actions']['package_cache'])
        button.connect('clicked',lambda b:self.review_storage_cleanup('package_cache'));row.add_suffix(button)
        row=self.note('Old system journals','Remove archived journal data older than 30 days. Current journal files are kept; diagnostic history is reduced.')
        button=Gtk.Button(label='Clean old journals',valign=Gtk.Align.CENTER,sensitive=data['system_actions']['system_logs'])
        button.connect('clicked',lambda b:self.review_storage_cleanup('system_logs'));row.add_suffix(button)
        if data['protected_crash_locations']:
            self.note('Protected system crash reports','Not included in user cleanup: '+', '.join(data['protected_crash_locations'])+'. Forge does not delete these protected crash directories in this build.')
        if data['errors']:
            self.note('Some locations could not be fully scanned','Sizes may be partial. '+str(len(data['errors']))+' scan notices. Inaccessible files are not claimed as reclaimable.')
        self.set_status('Scan complete · no files changed')

    def scan_storage(self):
        if self.locked or self.backend.busy or self.flatpaks.busy or self.cleaner.busy:return
        if DEMO:
            self.set_status('Demo mode: host storage scans and cleanup are disabled.')
            return
        self.busy_ui(True);self.set_status('Scanning approved cache, log, crash, and Trash locations…')
        def scanned(data,error):
            self.busy_ui(False)
            if error:self.message('Could not scan storage',error)
            else:self.storage_scan=data;self.storage_page()
        self.cleaner.run('scan',scanned)

    def review_storage_cleanup(self,action='clean'):
        if self.locked or self.backend.busy or self.flatpaks.busy or self.cleaner.busy:return
        if self.monitor_backend.busy or self.flatpak_monitor.busy:
            self.set_status('Let the update checks finish before cleaning storage.');return
        if DEMO:self.set_status('Demo mode: cleanup is disabled.');return
        if not self.storage_scan:return
        selected=[dict(item) for item in self.storage_scan['items'] if item['category'] in self.storage_categories]
        if action=='clean' and not selected:
            self.set_status('Select at least one cleanup category first.');return
        self.locked=True
        if action=='clean':
            body=f'{len(selected)} scanned entries · '+GLib.format_size(sum(item['size'] for item in selected))+'. Files that changed since scanning will be skipped. Deletion is permanent, including Trash. Close affected apps first; clearing caches can make their next launch slower.'
        elif action=='package_cache':body='Your distribution’s package tool will clean its download cache. Arch retains three cached versions; Fedora/Ubuntu may clear downloaded package files. This may require downloads again later. Administrator authentication is required.'
        else:body='The system journal tool will remove archived journal data older than 30 days. Current journals are preserved. This reduces diagnostic history and requires administrator authentication.'
        d=Adw.MessageDialog(transient_for=self.win,heading='Review storage cleanup',body=body)
        d.add_response('cancel','Cancel');d.add_response('apply','Clean selected' if action=='clean' else 'Run system cleanup')
        d.set_default_response('cancel');d.set_close_response('cancel');d.set_response_appearance('apply',Adw.ResponseAppearance.DESTRUCTIVE)
        extra=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        if selected and action=='clean':
            text='\n'.join(str(Path(item['root'])/item['path']) for item in selected[:40])
            if len(selected)>40:text+='\n… and '+str(len(selected)-40)+' more scanned entries.'
            label=Gtk.Label(label=text,xalign=0,wrap=True,selectable=True)
            scroll=Gtk.ScrolledWindow(min_content_height=100,max_content_height=220,propagate_natural_height=True);scroll.set_child(label);extra.append(scroll)
        check=Gtk.CheckButton();check.set_child(Gtk.Label(label='I reviewed the selection and understand that deleted data cannot be restored by Forge.',wrap=True,xalign=0))
        d.set_response_enabled('apply',False);check.connect('toggled',lambda b:d.set_response_enabled('apply',b.get_active()))
        extra.append(check);d.set_extra_child(extra)
        def answered(dialog,response):
            if response!='apply':self.locked=False;return
            self.busy_ui(True);self.set_status('Cleaning the selected storage category…')
            def finished(data,error):
                self.locked=False;self.busy_ui(False);self.storage_scan=None
                self.storage_page()
                if error:self.message('Cleanup did not complete',error+'\n\nSome steps may have completed. Scan again before retrying.')
                elif action=='clean':self.message('Cleanup finished',f"Removed {data['removed']} entries containing {GLib.format_size(data['bytes'])} of listed file data. Skipped {data['skipped']} changed or inaccessible entries. Scan again to refresh available disk space.")
                else:self.message('System cleanup finished',data['message']+'\n\nScan again to refresh the storage overview.')
            self.cleaner.run(action,finished,selected=selected if action=='clean' else None)
        d.connect('response',answered);d.present()

    def refresh_queue_count(self):
        count=len(self.queue)+len(self.flatpak_queue)
        self.review.set_label(f'Downloads ({count})')
        if hasattr(self,'queue_nav_label'):self.queue_nav_label.set_text(f'Downloads ({count})' if count else 'Downloads')

    def enqueue_flatpak_updates(self, apps):
        if self.locked or self.backend.busy or self.flatpaks.busy: return
        for app in apps:
            key = (app['scope'], app_ref(app))
            self.flatpak_queue[key] = dict(app)
        self.refresh_queue_count()
        self.navigate('Queue')

    def queue_all_app_updates(self,*args):
        if self.locked or self.backend.busy or self.flatpaks.busy or self.cleaner.busy:return
        if DEMO:
            self.enqueue_flatpak_updates([{'id':'org.gimp.GIMP','name':'GIMP','summary':'Sample update','version':'demo','branch':'stable','remote':'flathub','arch':'x86_64','scope':'user','kind':'app'}])
            return
        self.busy_ui(True);self.set_status('Finding app and runtime updates in both Flatpak installations…')
        def loaded(apps,errors):
            self.busy_ui(False)
            if errors:
                self.message('Could not gather every app update','\n'.join(errors)+'\n\nNo new updates were added. Retry after resolving the unavailable source.')
                return
            if not apps:
                self.set_status('No Flatpak app or runtime updates were reported.');return
            self.enqueue_flatpak_updates(apps)
        self.flatpaks.both('updates',loaded)

    def queue_flatpak_updates(self, scope):
        if self.locked or self.backend.busy or self.flatpaks.busy: return
        if DEMO:
            self.enqueue_flatpak_updates([{'id':'org.gimp.GIMP','name':'GIMP','summary':'Sample update','version':'demo','branch':'stable','remote':'flathub','arch':'x86_64','scope':scope,'kind':'app'}])
            return
        self.busy_ui(True)
        def loaded(text, error):
            self.busy_ui(False)
            if error:
                self.message('Could not queue Flatpak updates', error)
                return
            from flatpaks import parse_apps
            apps = parse_apps(text, scope, updates=True)
            if not apps:
                self.set_status('No Flatpak updates were reported for this installation.')
                return
            self.enqueue_flatpak_updates(apps)
        self.flatpaks.run('updates', scope, loaded)

    def dequeue_flatpak(self, key):
        if self.locked or self.backend.busy or self.flatpaks.busy: return
        self.flatpak_queue.pop(key, None)
        self.refresh_queue_count()
        self.clear()
        self.show_queue()

    def review_flatpak_queue(self, *args):
        if not self.flatpak_queue or self.locked or self.backend.busy or self.flatpaks.busy: return
        if DEMO:
            self.set_status('Demo mode: Flatpak updates can be queued, but cannot be applied.')
            return
        snapshot = list(self.flatpak_queue.items())
        self.locked = True
        dialog = Adw.MessageDialog(transient_for=self.win, heading='Review queued Flatpak updates', body='Only the selected apps and runtimes below are submitted for updating. Flatpak may also update required dependencies and related components. System packages in Downloads are reviewed separately. Nothing changes until you confirm.')
        dialog.add_response('cancel','Cancel')
        dialog.add_response('apply','Apply Flatpak updates')
        dialog.set_default_response('cancel'); dialog.set_close_response('cancel')
        dialog.set_response_appearance('apply',Adw.ResponseAppearance.SUGGESTED)
        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        for key, app in snapshot:
            line = Gtk.Box(spacing=12)
            line.append(self.flatpak_icon(app,32))
            scope = 'Just me' if app['scope']=='user' else 'All users'
            line.append(Gtk.Label(label=app['name']+' · '+scope+'\n'+app_ref(app),xalign=0,wrap=True))
            items.append(line)
        scroll = Gtk.ScrolledWindow(min_content_height=100,max_content_height=280,propagate_natural_height=True)
        scroll.set_child(items);dialog.set_extra_child(scroll)
        def answered(d,response):
            if response!='apply': self.locked=False;return
            batches = []
            for scope in ('user','system'):
                entries = [(key,app) for key,app in snapshot if app['scope']==scope]
                if entries: batches.append((scope,entries))
            self.busy_ui(True);self.transaction_activity([],True)
            self.activity_label.set_text('Updating queued Flatpaks…')
            self.activity_progress.set_text('Working…')
            for key,app in snapshot[:4]:self.activity_icons.append(self.flatpak_icon(app,36))
            def next_batch():
                if not batches:
                    self.locked=False;self.busy_ui(False);self.transaction_activity([],False)
                    self.refresh_queue_count();self.clear();self.show_queue()
                    self.set_status('Queued Flatpak updates completed.');self.check_updates()
                    return
                scope, entries = batches.pop(0)
                def finished(text,error):
                    # A zero exit status is not proof that the selected updates were applied.
                    def verified(output,verify_error):
                        from flatpaks import parse_apps
                        pending=parse_apps(output,scope,updates=True) if not verify_error else None
                        remaining={app_ref(app):app for app in pending} if pending is not None else {}
                        if pending is not None:
                            for key,app in entries:
                                if key[1] not in remaining:self.flatpak_queue.pop(key,None)
                                else:self.flatpak_queue[key]=remaining[key[1]]
                        self.refresh_queue_count();self.clear();self.show_queue()
                        unfinished=[key for key,app in entries if key in self.flatpak_queue]
                        if error or verify_error or unfinished:
                            self.locked=False;self.busy_ui(False);self.transaction_activity([],False)
                            detail=error or verify_error or f'{len(unfinished)} selected updates are still reported by the source.'
                            self.message('Some Flatpak updates remain',detail+'\n\nDownloads now keeps only unfinished or unverified selections. Retry after resolving the reported issue.');return
                        next_batch()
                    self.flatpaks.run('updates',scope,verified)
                self.flatpaks.run('update-many',scope,finished,app=[app for key,app in entries])
            next_batch()
        dialog.connect('response',answered);dialog.present()

    def show_queue(self):
        if not self.queue and not self.flatpak_queue:
            self.note('Your queue is clear', 'Add apps or updates from Discover, Library, Updates, or Flatpak apps.')
            return
        if self.queue:
            self.note('SYSTEM PACKAGE CHANGES','Native changes have their own dependency review.').add_css_class('section')
            for pid, action in list(self.queue.items()):
                name = package_parts(pid)[0]
                row = self.note(DISCOVER_APPS.get(name, (name,))[0], action.replace('Packages','') + ' · ' + name)
                row.add_prefix(app_icon(name, 40))
                button = Gtk.Button(icon_name='edit-delete-symbolic', tooltip_text='Remove from queue', valign=Gtk.Align.CENTER)
                button.connect('clicked', lambda b, p=pid: self.dequeue(p))
                row.add_suffix(button)
            row = self.note('Review system changes', 'Check required dependencies and every native package change.')
            button = Gtk.Button(label='Review system changes',css_classes=['suggested-action'],valign=Gtk.Align.CENTER)
            button.connect('clicked',self.resolve);row.add_suffix(button)
        if self.flatpak_queue:
            self.note('FLATPAK UPDATES','Apps and runtimes are grouped by installation. Remove anything you do not want to update.').add_css_class('section')
            for key,app in list(self.flatpak_queue.items()):
                scope = 'Just me' if app['scope']=='user' else 'All users'
                row = self.note(app['name'],'Update · '+scope+' · '+app_ref(app))
                row.add_prefix(self.flatpak_icon(app,40))
                button = Gtk.Button(icon_name='edit-delete-symbolic',tooltip_text='Remove Flatpak update from queue',valign=Gtk.Align.CENTER)
                button.connect('clicked',lambda b,k=key:self.dequeue_flatpak(k));row.add_suffix(button)
            row = self.note('Review Flatpak updates','Only queued references are submitted. Required related updates are resolved by Flatpak.')
            button = Gtk.Button(label='Review Flatpak updates',css_classes=['suggested-action'],valign=Gtk.Align.CENTER)
            button.connect('clicked',self.review_flatpak_queue);row.add_suffix(button)

    def dequeue(self, pid):
        if self.locked or self.backend.busy: return
        self.queue.pop(pid, None)
        self.refresh_queue_count()
        self.clear()
        self.show_queue()

    def resolve(self, *args):
        if self.locked or self.backend.busy: return
        if self.monitor_backend.busy or self.flatpaks.busy:
            self.set_status('Let the update check finish, then review your changes.')
            return
        if DEMO:
            self.set_status('Demo mode: system changes are disabled.')
            return
        # One action type per plan ensures the simulation matches the applied transaction.
        actions = set(self.queue.values())
        if len(actions) != 1:
            self.set_status('Review installs, removals, and updates separately. Keep one action type in the queue.')
            return
        if self.host['family'] == 'arch' and actions == {'UpdatePackages'}:
            if set(self.queue) != set(self.available_updates) or not self.available_updates:
                self.message('Review all Arch updates together', 'Arch is a rolling-release system. Use Review all updates from the Updates page rather than selecting a partial set.')
                return
        self.locked = True
        self.busy_ui(True)
        action = next(iter(actions))
        ids = list(self.queue)
        initial = assess_plan(action, ids, [])
        if initial['blocked']:
            self.locked = False
            self.busy_ui(False)
            self.message('Core package removal blocked', 'Forge will not remove these known system components:\n\n' + ', '.join(initial['blocked']) + '\n\nRemoving them can prevent the system from booting or working correctly.')
            return
        def resolved(results, error):
            self.busy_ui(False)
            if error:
                self.locked = False
                self.message('Cannot prepare transaction', error)
                return
            plan = assess_plan(action, ids, results)
            if plan['blocked'] or not plan['lines']:
                self.locked = False
                reason = ('The plan removes known core components: ' + ', '.join(plan['blocked'])) if plan['blocked'] else 'The package service did not return a package plan. Forge cannot safely show what will change.'
                self.message('Transaction blocked', reason)
                return
            body = '\n\n'.join(plan['warnings']) or 'Review the resolved changes below. System packages can affect other applications.'
            body += '\n\nAdministrator authentication is handled by your system. The final dependency resolution can change if repository metadata changes.'
            dialog = Adw.MessageDialog(transient_for=self.win, heading='Review system package changes', body=body)
            dialog.add_response('cancel', 'Cancel')
            dialog.add_response('apply', 'Apply changes')
            dialog.set_response_appearance('apply', Adw.ResponseAppearance.DESTRUCTIVE if plan['destructive'] else Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response('cancel')
            dialog.set_close_response('cancel')
            extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            for entry in plan['entries']:
                item = Gtk.Box(spacing=12)
                item.append(app_icon(entry['name'], 32))
                copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
                copy.append(Gtk.Label(label=entry['action'] + ' · ' + entry['name'], xalign=0, wrap=True))
                copy.append(Gtk.Label(label=f"{entry['version']} · {entry['arch']} · {entry['repo']}", xalign=0, selectable=True, wrap=True, css_classes=['subtitle', 'small']))
                item.append(copy)
                items.append(item)
            scroll = Gtk.ScrolledWindow(min_content_height=120, max_content_height=260, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroll.set_child(items)
            extra.append(scroll)
            if plan['destructive']:
                acknowledge = Gtk.CheckButton()
                acknowledge.set_child(Gtk.Label(label='I have reviewed the removals or downgrades and understand the risks.', wrap=True, xalign=0))
                dialog.set_response_enabled('apply', False)
                acknowledge.connect('toggled', lambda b: dialog.set_response_enabled('apply', b.get_active()))
                extra.append(acknowledge)
            dialog.set_extra_child(extra)
            def answer(d, response):
                if response != 'apply':
                    self.locked = False
                    self.set_status('Transaction cancelled. Your queue is unchanged.')
                    return
                self.busy_ui(True)
                self.transaction_activity(ids, True)
                def applied(results, error):
                    self.busy_ui(False)
                    self.transaction_activity([], False)
                    self.locked = False
                    if error: self.message('Could not finish the changes', error + '\n\nSome changes may already have completed. Recheck your Library and Updates before retrying. Forge has kept your selections for review.')
                    else:
                        def complete(pending=None,verify_error=None):
                            if pending is not None:
                                by_name={(package_parts(pid)[0],package_parts(pid)[2]):pid for pid in pending}
                                for pid in ids:
                                    self.queue.pop(pid,None)
                                    replacement=by_name.get((package_parts(pid)[0],package_parts(pid)[2]))
                                    if replacement:self.queue[replacement]='UpdatePackages'
                                self.available_updates=pending
                                self.update_state.accept([('Package',(2,pid,'')) for pid in pending])
                                self.refresh_update_identity()
                            elif not verify_error:
                                for pid in ids:self.queue.pop(pid,None)
                            self.locked=False;self.busy_ui(False)
                            self.refresh_queue_count();self.clear();self.show_queue()
                            if verify_error:self.message('Changes applied; update check unavailable',verify_error+'\n\nSelections remain in Downloads until they can be verified.')
                            elif self.queue and action=='UpdatePackages':self.message('Some system updates remain','The system still reports selected updates. Downloads has been refreshed with the remaining versions.')
                            else:self.set_status(restart_message(results))
                            if any(k=='RequireRestart' and v[0] in (2,3,4,5,6) for k,v in results):self.message('Changes applied',restart_message(results))
                            self.check_updates()
                        if action=='UpdatePackages':
                            self.locked=True;self.busy_ui(True)
                            def verified(current,verify_error):complete([v[1] for k,v in current if k=='Package'] if not verify_error else None,verify_error)
                            self.backend.run('GetUpdates',GLib.Variant('(t)',(0,)),verified)
                        else:complete()
                self.backend.run(action, transaction_args(action, ids), applied)
            dialog.connect('response', answer)
            dialog.present()
        self.backend.run(action, transaction_args(action, ids, True), resolved)

    def message(self, title, body):
        self.set_status(title)
        d = Adw.MessageDialog(transient_for=self.win, heading=title, body=body)
        d.add_response('ok', 'Close')
        d.present()

if __name__ == '__main__':
    if os.geteuid() == 0:
        print('Run Forge as your normal user. The system requests administrator authentication when needed.', file=sys.stderr)
        sys.exit(1)
    if not Gtk.init_check():
        print('Forge needs a graphical desktop session (Wayland or X11).', file=sys.stderr)
        sys.exit(1)
    Forge().run([a for a in sys.argv if a not in ('--demo', '--background')])
