"""Optional StatusNotifierItem tray integration; no host processes or root access."""
from pathlib import Path
import os
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gio, GLib, GdkPixbuf

ITEM_XML = '''<node><interface name="org.kde.StatusNotifierItem">
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="IconName" type="s" access="read"/><property name="IconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionIconName" type="s" access="read"/><property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
<property name="ItemIsMenu" type="b" access="read"/><property name="Menu" type="o" access="read"/>
<signal name="NewIcon"/><signal name="NewToolTip"/><signal name="NewStatus"><arg type="s"/></signal>
</interface></node>'''
MENU_XML = '''<node><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/><property name="Status" type="s" access="read"/>
</interface></node>'''

def icon_pixmap(path):
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 32, 32, True)
        source = pixbuf.get_pixels()
        channels, stride = pixbuf.get_n_channels(), pixbuf.get_rowstride()
        pixels = bytearray()
        for y in range(pixbuf.get_height()):
            for x in range(pixbuf.get_width()):
                offset = y * stride + x * channels
                pixels.extend((source[offset + 3] if channels == 4 else 255, *source[offset:offset + 3]))
        return [(pixbuf.get_width(), pixbuf.get_height(), bytes(pixels))]
    except GLib.Error: return []

class Tray:
    def __init__(self, app_id, show, check, quit_callback, changed=None):
        self.app_id, self.show, self.check, self.quit = app_id, show, check, quit_callback
        self.available = False
        self.reason = 'Checking desktop tray support…'
        self.changed = changed or (lambda: None)
        self.registered = False
        self.count = None
        self.connection = None
        self.pixmaps = {}
        base = Path(__file__).resolve().parent
        roots = [base / 'data', base.parent / 'share/icons/hicolor/128x128/apps']
        for suffix in ('', '.Updates'):
            path = next((root / (app_id + suffix + '.png') for root in roots if (root / (app_id + suffix + '.png')).is_file()), None)
            self.pixmaps[suffix] = icon_pixmap(path) if path else []
        self.owner = Gio.bus_own_name(Gio.BusType.SESSION, app_id + '.Tray.p' + str(os.getpid()), Gio.BusNameOwnerFlags.NONE, self.acquired, self.name_acquired, self.name_lost)

    @property
    def icon_name(self): return self.app_id + ('.Updates' if self.count else '')

    def acquired(self, connection, name):
        self.connection = connection
        connection.register_object('/StatusNotifierItem', Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0], self.item_method, self.item_property, None)
        connection.register_object('/MenuBar', Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0], self.menu_method, self.menu_property, None)
        connection.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged', '/org/freedesktop/DBus', 'org.kde.StatusNotifierWatcher', Gio.DBusSignalFlags.NONE, self.watcher_changed)
        connection.signal_subscribe('org.kde.StatusNotifierWatcher', 'org.kde.StatusNotifierWatcher', None, '/StatusNotifierWatcher', None, Gio.DBusSignalFlags.NONE, self.host_changed)

    def name_acquired(self, connection, name):
        self.register()

    def name_lost(self, connection, name):
        self.set_available(False, 'The desktop tray connection is unavailable.')

    def set_available(self, value, reason):
        self.available = value
        self.reason = reason
        self.changed()

    def host_changed(self, connection, sender, path, interface, signal, params, *unused):
        if signal == 'StatusNotifierHostRegistered': self.register()
        elif signal == 'StatusNotifierHostUnregistered': self.set_available(False, 'No desktop tray host is registered.')

    def watcher_changed(self, connection, sender, path, interface, signal, params, *unused):
        self.registered = False
        self.set_available(False, 'No desktop tray host is available. Use the dock or enable tray support.')
        if params.unpack()[2]: self.register()

    def register(self):
        if not self.connection: return
        def host_ready(connection, result, *unused):
            try:
                value=connection.call_finish(result).unpack()[0]
                if hasattr(value,'unpack'):value=value.unpack()
                if value:self.set_available(True,'Desktop tray support is active.')
                else:self.set_available(False,'The tray watcher has no visible tray host. Using the dock instead.')
            except GLib.Error:
                # Never hide the only window if a visible tray host cannot be verified.
                self.set_available(False,'Tray host visibility could not be verified. Using the dock instead.')
        def done(connection, result, *unused):
            try:
                connection.call_finish(result)
                self.registered=True
                connection.call('org.kde.StatusNotifierWatcher','/StatusNotifierWatcher','org.freedesktop.DBus.Properties','Get',GLib.Variant('(ss)',('org.kde.StatusNotifierWatcher','IsStatusNotifierHostRegistered')),None,Gio.DBusCallFlags.NONE,5000,None,host_ready)
            except GLib.Error:
                self.set_available(False,'No desktop tray host is available. On GNOME, enable AppIndicator support or use the dock.')
        self.connection.call('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher', 'org.kde.StatusNotifierWatcher', 'RegisterStatusNotifierItem', GLib.Variant('(s)', (self.app_id + '.Tray.p' + str(os.getpid()),)), None, Gio.DBusCallFlags.NONE, 5000, None, done)

    def item_method(self, connection, sender, path, interface, method, params, invocation):
        self.show()
        invocation.return_value(None)

    def item_property(self, connection, sender, path, interface, prop):
        text = 'Update status not yet available' if self.count is None else f'{self.count} software updates available' if self.count else 'No software updates reported'
        suffix = '.Updates' if self.count else ''
        values = {'Category': ('s', 'ApplicationStatus'), 'Id': ('s', self.app_id), 'Title': ('s', 'Forge'), 'Status': ('s', 'Active'),
                  'IconName': ('s', self.icon_name), 'IconPixmap': ('a(iiay)', self.pixmaps[suffix]), 'AttentionIconName': ('s', self.app_id + '.Updates'),
                  'ToolTip': ('(sa(iiay)ss)', (self.icon_name, self.pixmaps[suffix], 'Forge', text)), 'ItemIsMenu': ('b', False), 'Menu': ('o', '/MenuBar')}
        signature, value = values[prop]
        return GLib.Variant(signature, value)

    def menu_props(self, item):
        return {'label': GLib.Variant('s', {1: 'Open Forge', 2: 'Check for updates', 3: 'Quit Forge'}[item]), 'enabled': GLib.Variant('b', True), 'visible': GLib.Variant('b', True)}

    def menu_method(self, connection, sender, path, interface, method, params, invocation):
        args = params.unpack()
        if method == 'GetLayout':
            children = [GLib.Variant('(ia{sv}av)', (i, self.menu_props(i), [])) for i in (1, 2, 3)]
            invocation.return_value(GLib.Variant('(u(ia{sv}av))', (1, (0, {'children-display': GLib.Variant('s', 'submenu')}, children))))
        elif method == 'GetGroupProperties':
            invocation.return_value(GLib.Variant('(a(ia{sv}))', ([(i, self.menu_props(i)) for i in args[0] if i in (1, 2, 3)],)))
        elif method == 'AboutToShow': invocation.return_value(GLib.Variant('(b)', (False,)))
        elif method == 'Event':
            if args[1] == 'clicked':
                callback = {1: self.show, 2: self.check, 3: self.quit}.get(args[0])
                if callback: GLib.idle_add(lambda: (callback(), False)[1])
            invocation.return_value(None)

    def menu_property(self, connection, sender, path, interface, prop):
        return {'Version': GLib.Variant('u', 3), 'TextDirection': GLib.Variant('s', 'ltr'), 'Status': GLib.Variant('s', 'normal')}[prop]

    def update(self, count):
        self.count = count
        if self.connection:
            for signal in ('NewIcon', 'NewToolTip'):
                self.connection.emit_signal(None, '/StatusNotifierItem', 'org.kde.StatusNotifierItem', signal, None)
