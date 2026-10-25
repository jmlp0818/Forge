"""Cached, asynchronous publisher-artwork refresh for the home storefront."""
from pathlib import Path
import base64
import hashlib
import json
import sys
import time
from gi.repository import Gio,GLib

class Catalog:
    def __init__(self):
        root=Path(GLib.get_user_cache_dir())
        if not Path('/.flatpak-info').exists():root=root/'forge'
        self.root=root/'catalog';self.busy=False
        self.records={}
        try:self.records=json.loads((self.root/'catalog.json').read_text())['records']
        except (OSError,ValueError,KeyError):pass

    def get(self,identifier):return self.records.get(identifier,{})
    def image(self,identifier,kind):
        record=self.get(identifier)
        name=record.get(kind)
        if not name or Path(name).name!=name:return None
        path=self.root/name
        return path if path.is_file() else None

    def refresh(self,ids,featured,done,force=False):
        if self.busy:return
        try:
            if not force and time.time()-(self.root/'catalog.json').stat().st_mtime<86400:
                done(None);return
        except OSError:pass
        try:
            helper=Path(__file__).with_name('catalog_host.py')
            args=['flatpak-spawn','--host','python3','-I','-c',helper.read_text()] if Path('/.flatpak-info').exists() else [sys.executable,'-I',str(helper)]
            process=Gio.Subprocess.new(args,Gio.SubprocessFlags.STDIN_PIPE|Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_PIPE)
        except (OSError,GLib.Error) as error:done(str(error));return
        self.busy=True
        def finished(proc,result,*unused):
            self.busy=False
            try:
                ok,stdout,stderr=proc.communicate_utf8_finish(result)
                data=json.loads(stdout)
                if not proc.get_successful():raise ValueError(data.get('error') or stderr)
                self.root.mkdir(parents=True,exist_ok=True)
                for item in data.get('apps',[]):
                    identifier=item['id'];record={**self.records.get(identifier,{}),**{k:v for k,v in item.items() if k not in ('icon','screenshot')}}
                    for kind in ('icon','screenshot'):
                        if item.get(kind):
                            image=base64.b64decode(item[kind],validate=True)
                            if len(image)>5_000_000:continue
                            name=hashlib.sha256((identifier+kind).encode()).hexdigest()+'.image'
                            target=self.root/name
                            temp=target.with_suffix('.tmp');temp.write_bytes(image);temp.replace(target)
                            record[kind]=name
                    self.records[identifier]=record
                target=self.root/'catalog.json';temp=target.with_suffix('.tmp')
                temp.write_text(json.dumps({'records':self.records}));temp.replace(target)
                done(None)
            except (OSError,ValueError,KeyError,GLib.Error) as error:done(str(error))
        request={'ids':list(ids),'featured':list(featured),'refresh':force}
        process.communicate_utf8_async(json.dumps(request),None,finished)
