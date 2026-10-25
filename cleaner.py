"""Asynchronous access to the fixed host cleanup helper."""
from pathlib import Path
import json
import sys
from gi.repository import Gio,GLib

class Cleaner:
    def __init__(self,journal=None):self.busy=False;self.journal=journal
    def run(self,action,done,selected=None):
        if self.busy:done(None,'A storage operation is already running.');return
        try:
            if action!='scan' and self.journal:self.journal.begin(action)
            helper=Path(__file__).with_name('cleanup_host.py')
            if Path('/.flatpak-info').exists():
                args=['flatpak-spawn','--host','python3','-I','-c',helper.read_text()]
            else:args=[sys.executable,'-I',str(helper)]
            process=Gio.Subprocess.new(args,Gio.SubprocessFlags.STDIN_PIPE|Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_PIPE)
        except (OSError,GLib.Error) as error:done(None,str(error));return
        self.busy=True
        request={'action':action}
        if selected is not None:request['selected']=selected
        def finished(proc,result,*unused):
            self.busy=False
            try:
                ok,stdout,stderr=proc.communicate_utf8_finish(result)
                data=json.loads(stdout)
                error=data.get('error') or stderr or 'Storage operation failed.' if not proc.get_successful() or 'error' in data else None
                if action!='scan' and self.journal:self.journal.finish(error)
                done(None if error else data,error)
            except (GLib.Error,ValueError) as error:done(None,str(error))
        process.communicate_utf8_async(json.dumps(request),None,finished)
