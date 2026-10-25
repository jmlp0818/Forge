"""Validated, shell-free bridge to the host Flatpak installation."""
from pathlib import Path
import platform
import configparser
import re
from gi.repository import Gio, GLib

COLUMNS = 'application:f,name:f,description:f,version:f,branch:f,origin:f,arch:f'

def valid_id(value):
    return isinstance(value, str) and len(value) <= 255 and bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+){2,}', value))

def token(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('Invalid Flatpak source, architecture, or branch.')
    return value

def scope_flag(scope):
    if scope not in ('user', 'system'): raise ValueError('Unsupported Flatpak installation.')
    return '--' + scope

def app_ref(app):
    if not valid_id(app.get('id')): raise ValueError('Invalid application ID.')
    return ('runtime/' if app.get('kind') == 'runtime' else 'app/') + app['id'] + '/' + token(app.get('arch') or host_arch()) + '/' + token(app.get('branch') or 'stable')

def host_arch(): return {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(platform.machine(), platform.machine())

def command(operation, scope='user', app=None, query=''):
    flag = scope_flag(scope)
    if operation == 'list': return ['flatpak', 'list', flag, '--app', '--columns=' + COLUMNS]
    if operation == 'updates': return ['flatpak', 'remote-ls', flag, '--updates', '--columns=ref:f,' + COLUMNS]
    if operation == 'search':
        if not query.strip() or len(query) > 300: raise ValueError('Enter a shorter search query.')
        return ['flatpak', 'search', flag, '--columns=application:f,name:f,description:f,version:f,branch:f,remotes:f', '--', query.strip()]
    if operation == 'sources': return ['flatpak', 'remotes', flag, '--columns=name:f,title:f,url:f,options:f']
    if operation == 'add-flathub':
        if scope != 'user': raise ValueError('Flathub setup is offered for your account only.')
        return ['flatpak', 'remote-add', '--user', '--if-not-exists', 'flathub', 'https://dl.flathub.org/repo/flathub.flatpakrepo']
    if operation == 'update-many':
        if not isinstance(app, list) or not app: raise ValueError('No Flatpak updates selected.')
        refs = list(dict.fromkeys(app_ref(item) for item in app))
        return ['flatpak', 'update', flag, '--assumeyes', *refs]
    if operation == 'update-all': return ['flatpak', 'update', flag, '--assumeyes']
    if app is None: raise ValueError('Choose an application first.')
    ref = app_ref(app)
    if operation == 'inspect': return ['flatpak', 'remote-info', flag, '--show-metadata', token(app['remote']), ref]
    if operation == 'install': return ['flatpak', 'install', flag, '--app', '--assumeyes', token(app['remote']), ref]
    if operation == 'remove': return ['flatpak', 'uninstall', flag, '--app', '--assumeyes', ref]
    if operation == 'update': return ['flatpak', 'update', flag, '--runtime' if app.get('kind') == 'runtime' else '--app', '--assumeyes', ref]
    raise ValueError('Unsupported Flatpak operation.')

def parse_apps(text, scope, search=False, updates=False):
    apps = []
    for line in text.splitlines():
        fields = line.split('\t')
        kind = 'app'
        if updates:
            if len(fields) < 8: continue
            ref, *fields = fields
            parts = ref.split('/')
            if len(parts) != 4 or parts[0] not in ('app','runtime'): continue
            kind = parts[0]
        if len(fields) < 6 or not valid_id(fields[0]): continue
        identifier, name, summary, version, branch, remotes = fields[:6]
        arch = fields[6] if len(fields) > 6 and not search else host_arch()
        for remote in remotes.split(',') if search else [remotes]:
            remote = remote.strip()
            try:
                app = {'id': identifier, 'name': name or identifier, 'summary': summary, 'version': version, 'branch': branch or 'stable', 'remote': token(remote) if remote else '', 'arch': token(arch), 'scope': scope, 'kind': kind}
                app_ref(app)
                apps.append(app)
            except ValueError: continue
    return apps

def permissions_summary(metadata):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    try: config.read_string(metadata)
    except configparser.Error: return 'The publisher metadata could not be summarized. Review the technical details below.'
    context = config['Context'] if config.has_section('Context') else {}
    shared = context.get('shared', '').split(';')
    sockets = context.get('sockets', '').split(';')
    files = [value for value in context.get('filesystems', '').split(';') if value]
    devices = context.get('devices', '').split(';')
    lines = []
    if 'network' in shared: lines.append('• Internet and network access')
    if 'pulseaudio' in sockets: lines.append('• Audio service access (playback and potentially recording)')
    if 'x11' in sockets or 'fallback-x11' in sockets: lines.append('• X11 desktop access when that display mode is used')
    if 'all' in devices: lines.append('• Broad hardware-device access')
    elif 'dri' in devices: lines.append('• Graphics acceleration')
    if files: lines.append('• File access: ' + ', '.join(files))
    if config.has_section('Session Bus Policy') or config.has_section('System Bus Policy'):
        lines.append('• Access to selected desktop/system services')
    if not lines: lines.append('No broad static permissions found in this metadata.')
    return '\n'.join(lines) + '\n\nApps may also request access through desktop dialogs. Local overrides can change effective permissions.'

class Flatpaks:
    def __init__(self, status=lambda text: None, journal=None):
        self.status = status
        self.busy = False
        self.process = None
        self.journal = journal

    def run(self, operation, scope, done, app=None, query=''):
        if self.busy:
            done('', 'Another Flatpak operation is running.')
            return
        try:
            argv = command(operation, scope, app, query)
            writing = operation in ('install', 'remove', 'update', 'update-all', 'update-many', 'add-flathub')
            if writing and self.journal: self.journal.begin(operation)
            if Path('/.flatpak-info').exists():
                argv = ['flatpak-spawn', '--host', '--env=LC_ALL=C', *argv]
            launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
            launcher.setenv('LC_ALL', 'C', True)
            self.process = launcher.spawnv(argv)
        except (GLib.Error, ValueError, OSError) as error:
            done('', str(error))
            return
        self.busy = True
        output = []
        read_errors = []
        stream = Gio.DataInputStream.new(self.process.get_stdout_pipe())
        process = self.process
        def finished(proc, result, *unused):
            try:
                proc.wait_finish(result)
                ok = proc.get_successful()
                error = '\n'.join(read_errors) or (None if ok else '\n'.join(output[-30:]) or 'The host Flatpak command failed.')
            except GLib.Error as error_value: error = error_value.message
            self.busy = False
            self.process = None
            if writing and self.journal: self.journal.finish(error)
            done('\n'.join(output), error)
        def line_read(reader, result, *unused):
            try:
                line, length = reader.read_line_finish_utf8(result)
                if line is None:
                    process.wait_async(None, finished)
                    return
                output.append(line)
                if operation in ('install', 'remove', 'update', 'update-all', 'update-many', 'add-flathub') and line.strip(): self.status(line[-250:])
                reader.read_line_async(GLib.PRIORITY_DEFAULT, None, line_read)
            except (GLib.Error, UnicodeError) as error:
                read_errors.append('Could not read the complete Flatpak result: ' + str(error))
                process.wait_async(None, finished)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, line_read)

    def both(self, operation, done, query=''):
        records, errors = [], []
        def one(scope):
            def loaded(text, error):
                if error: errors.append(scope + ': ' + error)
                else: records.extend(parse_apps(text, scope, operation == 'search', operation == 'updates'))
                if scope == 'user': one('system')
                else: done(records, errors)
            self.run(operation, scope, loaded, query=query)
        one('user')
