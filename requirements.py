"""First-run host checks and fixed prerequisite installation commands."""
from pathlib import Path
from gi.repository import Gio,GLib

PACKAGE_MAP={
    'fedora':{'packagekit':'PackageKit','python':'python3','flatpak':'flatpak'},
    'ubuntu':{'packagekit':'packagekit','python':'python3','flatpak':'flatpak'},
    'debian':{'packagekit':'packagekit','python':'python3','flatpak':'flatpak'},
    'arch':{'packagekit':'packagekit','python':'python','flatpak':'flatpak'},
}

def install_command(family,missing):
    packages=PACKAGE_MAP.get(family)
    if not packages:raise ValueError('Automatic prerequisite installation is unavailable for this distribution.')
    names=[packages[key] for key in ('packagekit','python','flatpak') if key in missing]
    if not names:raise ValueError('No required host components are missing.')
    if family=='fedora':return ['pkexec','dnf','install','--assumeyes',*names]
    if family in ('ubuntu','debian'):return ['pkexec','apt-get','install','--yes',*names]
    # Never refresh Arch databases separately from the upgrade transaction.
    return ['pkexec','pacman','-S','--needed','--noconfirm',*names]

class Requirements:
    def __init__(self):self.busy=False

    def command(self,args,done):
        if Path('/.flatpak-info').exists():args=['flatpak-spawn','--host',*args]
        try:process=Gio.Subprocess.new(args,Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as error:done('',error.message);return
        def finished(proc,result,*unused):
            try:
                ok,out,err=proc.communicate_utf8_finish(result)
                done(out,None if proc.get_successful() else out or 'The host command did not complete.')
            except GLib.Error as error:done('',error.message)
        process.communicate_utf8_async(None,None,finished)

    def check(self,done):
        if self.busy:return
        self.busy=True
        missing=[];issues=[];details=[]
        def host_checks():
            def python_checked(out,error):
                if error:missing.append('python')
                else:details.append('Host Python available')
                def flatpak_checked(out,error):
                    if error:missing.append('flatpak')
                    else:details.append('Host Flatpak available')
                    self.busy=False;done(missing,issues,details)
                self.command(['flatpak','--version'],flatpak_checked)
            self.command(['python3','--version'],python_checked)
        def connected(source,result,*unused):
            try:
                bus=Gio.bus_get_finish(result)
                def checked(connection,reply,*unused):
                    try:
                        props=connection.call_finish(reply).unpack()[0]
                        backend=props.get('BackendName','unknown')
                        details.append('System package service: '+backend)
                        if backend in ('dummy','unknown',''):issues.append('PackageKit has no usable package backend. Install the backend provided by your distribution.')
                    except GLib.Error as error:
                        if 'ServiceUnknown' in error.message or 'not provided by any .service' in error.message:missing.append('packagekit')
                        else:issues.append('Package service: '+error.message)
                    host_checks()
                bus.call('org.freedesktop.PackageKit','/org/freedesktop/PackageKit','org.freedesktop.DBus.Properties','GetAll',GLib.Variant('(s)',('org.freedesktop.PackageKit',)),None,Gio.DBusCallFlags.NONE,15000,None,checked)
            except GLib.Error as error:issues.append(error.message);host_checks()
        Gio.bus_get(Gio.BusType.SYSTEM,None,connected)

    def install(self,family,missing,done):
        try:args=install_command(family,missing)
        except ValueError as error:done('',str(error));return
        self.busy=True
        def finished(out,error):self.busy=False;done(out,error)
        self.command(args,finished)
