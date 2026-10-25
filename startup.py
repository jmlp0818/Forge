"""Login startup through the desktop portal; native source runs use XDG autostart."""
from pathlib import Path
import sys
import uuid
from gi.repository import Gio, GLib

def desktop_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$') + '"'

class Startup:
    def __init__(self, app_id, script):
        self.app_id, self.script = app_id, Path(script).resolve()
        self.busy = False

    def set(self, enabled, minimized, done, native_dir=None):
        if self.busy:
            done(False, 'A desktop permission request is already open.')
            return
        if not Path('/.flatpak-info').exists() or native_dir is not None:
            target = (Path(native_dir) if native_dir else Path(GLib.get_user_config_dir()) / 'autostart') / (self.app_id + '.desktop')
            try:
                if enabled:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    command = desktop_quote(sys.executable) + ' ' + desktop_quote(self.script) + (' --background' if minimized else '')
                    target.write_text('[Desktop Entry]\nType=Application\nName=Forge\nComment=Check for app and system updates\nExec=' + command + '\nIcon=' + self.app_id + '\nTerminal=false\nX-GNOME-Autostart-enabled=true\n')
                else: target.unlink(missing_ok=True)
                done(enabled, None)
            except OSError as error: done(False, str(error))
            return
        self.busy = True
        subscriptions = []
        completed = [False]
        bus = [None]
        timer = [None]
        def finish(allowed, error):
            if completed[0]: return
            completed[0] = True
            self.busy = False
            if timer[0]: GLib.source_remove(timer[0])
            if bus[0]:
                for subscription in subscriptions: bus[0].signal_unsubscribe(subscription)
            done(allowed, error)
        def response(connection, sender, path, interface, signal, params, *unused):
            code, values = params.unpack()
            if code != 0: finish(False, 'The desktop declined or cancelled the startup request.')
            else:
                allowed = bool(values.get('autostart', False))
                finish(allowed, None if allowed == enabled else 'The desktop did not grant the requested startup setting.')
        def called(connection, result, *unused):
            try: connection.call_finish(result)
            except GLib.Error as error: finish(False, error.message)
        def connected(source, result, *unused):
            try:
                connection = Gio.bus_get_finish(result)
                bus[0] = connection
                token = 'forge_' + uuid.uuid4().hex
                sender = connection.get_unique_name()[1:].replace('.', '_')
                path = '/org/freedesktop/portal/desktop/request/' + sender + '/' + token
                subscriptions.append(connection.signal_subscribe('org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request', 'Response', path, None, Gio.DBusSignalFlags.NONE, response))
                options = {'handle_token': GLib.Variant('s', token), 'reason': GLib.Variant('s', 'Check for software updates after you sign in.'), 'autostart': GLib.Variant('b', enabled), 'commandline': GLib.Variant('as', ['forge', '--background'] if minimized else ['forge']), 'dbus-activatable': GLib.Variant('b', False)}
                connection.call('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop', 'org.freedesktop.portal.Background', 'RequestBackground', GLib.Variant('(sa{sv})', ('', options)), GLib.VariantType.new('(o)'), Gio.DBusCallFlags.NONE, 10000, None, called)
            except GLib.Error as error: finish(False, error.message)
        timer[0] = GLib.timeout_add_seconds(120, lambda: (finish(False, 'The desktop startup request timed out.'), False)[1])
        Gio.bus_get(Gio.BusType.SESSION, None, connected)
