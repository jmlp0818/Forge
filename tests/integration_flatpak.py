"""Real install/update/remove in a disposable installation and local repo.

Run explicitly: python3 tests/integration_flatpak.py
Requires Flatpak. No normal user package, source, or app data is changed.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gi.repository import GLib
from flatpaks import Flatpaks,parse_apps
from operations import OperationJournal


def main():
    with tempfile.TemporaryDirectory(prefix='forge-integration-') as folder:
        base=Path(folder);repo=base/'repo';stage=base/'stage';install=base/'installation'
        env=dict(os.environ,FLATPAK_USER_DIR=str(install))
        os.environ['FLATPAK_USER_DIR']=str(install)
        for key,part in [('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_STATE_HOME','state')]:os.environ[key]=str(base/part)
        def run(*args):return subprocess.run(args,env=env,check=True,text=True,capture_output=True).stdout
        binary=stage/'files/bin/fixture';binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\n# version 1\nexit 0\n');binary.chmod(0o755)
        (stage/'metadata').write_text('[Application]\nname=io.github.jmlp0818.ForgeTestFixture\nruntime=org.gnome.Platform/x86_64/51\nsdk=org.gnome.Platform/x86_64/51\ncommand=fixture\n')
        run('flatpak','build-finish',str(stage))
        run('flatpak','build-export',str(repo),str(stage),'stable')
        # This exception is limited to the temporary local test repo.
        run('flatpak','remote-add','--user','--no-gpg-verify','fixture',repo.as_uri())
        run('flatpak','install','--user','--no-deps','-y','fixture','io.github.jmlp0818.ForgeTestFixture')
        first=run('flatpak','info','--user','--show-commit','io.github.jmlp0818.ForgeTestFixture').strip()
        binary.write_text('#!/bin/sh\n# version 2\nexit 0\n')
        run('flatpak','build-export',str(repo),str(stage),'stable')
        client=Flatpaks(journal=OperationJournal('flatpak',base/'journal'))
        def invoke(operation,app=None):
            loop=GLib.MainLoop();reply=[]
            def done(text,error):reply.append((text,error));loop.quit()
            def timeout():reply.append(('', 'test timeout'));loop.quit();return False
            timer=GLib.timeout_add_seconds(20,timeout)
            client.run(operation,'user',done,app=app)
            loop.run();GLib.source_remove(timer)
            assert len(reply)==1,reply
            assert reply[0][1] is None,reply
            return reply[0][0]
        pending=parse_apps(invoke('updates'),'user',updates=True)
        assert len(pending)==1,pending
        assert pending[0]['id']=='io.github.jmlp0818.ForgeTestFixture'
        invoke('update-many',pending)
        assert parse_apps(invoke('updates'),'user',updates=True)==[]
        second=run('flatpak','info','--user','--show-commit','io.github.jmlp0818.ForgeTestFixture').strip()
        assert first!=second
        assert client.journal.pending() is None
        invoke('remove',pending[0])
        assert parse_apps(invoke('list'),'user')==[]
        print('PASS: real isolated install -> pending update -> scoped update -> recheck -> uninstall; normal user installation untouched.')


if __name__=='__main__':main()
