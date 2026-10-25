#!/usr/bin/env python3
"""GitHub release packaging, AI-assisted. Not a Flathub submission manifest.

Builds a Python-only bundle from this source tree, without compiling code or
installing anything on the host. Requires an already installed GNOME Platform 51.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
APP_ID = 'io.github.jmlp0818.Forge'
VERSION = '0.15.0'
EPOCH = 1792800000  # 2026-10-24 UTC; source archive timestamps are fixed.
RUNTIME = 'org.gnome.Platform'
BRANCH = '51'


def install(prefix):
    prefix=Path(prefix)
    def copy(source,relative,executable=False):
        destination=prefix/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/source,destination)
        destination.chmod(0o755 if executable else 0o644)
    for source in sorted(ROOT.glob('*.py')):
        if source.name in ('packaging.py','prepare_appstream.py'):continue
        copy(source.name,'bin/'+('forge' if source.name=='forge.py' else source.name),source.name=='forge.py')
    copy('data/'+APP_ID+'.desktop','share/applications/'+APP_ID+'.desktop')
    copy('data/'+APP_ID+'.metainfo.xml','share/metainfo/'+APP_ID+'.metainfo.xml')
    for suffix in ('.svg','.Updates.svg','.png','.Updates.png'):
        folder='scalable' if suffix.endswith('.svg') else '128x128'
        copy('data/'+APP_ID+suffix,'share/icons/hicolor/'+folder+'/apps/'+APP_ID+suffix)
    for name in ('sources.json','ICONS.md'):copy('data/app-icons/'+name,'share/forge/app-icons/'+name)
    copy('LICENSE','share/licenses/'+APP_ID+'/LICENSE')
    from prepare_appstream import prepare
    prepare(prefix)


def source_files():
    # An explicit release tree excludes caches, VCS data, tokens, and build outputs.
    roots=[*ROOT.glob('*.py'),*ROOT.glob('*.md'),ROOT/'LICENSE',ROOT/'.gitignore',ROOT/(APP_ID+'.json')]
    for folder in ('data','tests','docs','.github'):
        roots.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    return sorted(set(p for p in roots if p.is_file()),key=lambda p:p.relative_to(ROOT).as_posix())


def source_archive(path):
    with Path(path).open('wb') as file:
        with gzip.GzipFile(fileobj=file,mode='wb',filename='',mtime=EPOCH) as zipped:
            with tarfile.open(fileobj=zipped,mode='w') as archive:
                for source in source_files():
                    data=source.read_bytes()
                    info=tarfile.TarInfo('Forge-'+VERSION+'/'+source.relative_to(ROOT).as_posix())
                    info.size=len(data);info.mode=0o755 if source.name in ('forge.py','packaging.py') else 0o644
                    info.mtime=EPOCH;info.uid=info.gid=0;info.uname=info.gname=''
                    archive.addfile(info,io.BytesIO(data))


def run(*argv):
    result=subprocess.run(argv,text=True,capture_output=True)
    if result.returncode:raise RuntimeError(' '.join(argv)+'\n'+result.stderr.strip())
    return result.stdout.strip()


def build(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    source=output/('Forge-'+VERSION+'-source.tar.gz');source_archive(source)
    arch={'amd64':'x86_64','arm64':'aarch64'}.get(platform.machine(),platform.machine())
    if arch!='x86_64':raise RuntimeError('Only x86_64 has been validated for this preview.')
    runtime_ref=RUNTIME+'/'+arch+'/'+BRANCH
    runtime_commit=run('flatpak','info','--show-commit',runtime_ref)
    manifest=json.loads((ROOT/(APP_ID+'.json')).read_text())
    with tempfile.TemporaryDirectory(prefix='forge-build-') as directory:
        stage=Path(directory)/'build';repo=Path(directory)/'repo'
        # The runtime is also the build environment: pure Python, no compiler/SDK needed.
        run('flatpak','build-init',str(stage),APP_ID,RUNTIME,RUNTIME,BRANCH)
        install(stage/'files')
        run('flatpak','build-finish','--command=forge',*manifest['finish-args'],str(stage))
        run('flatpak','build-export','--timestamp=2026-10-24T00:00:00Z',str(repo),str(stage),'stable')
        bundle=output/('Forge-'+VERSION+'.flatpak')
        run('flatpak','build-bundle','--runtime-repo=https://flathub.org/repo/flathub.flatpakrepo',str(repo),str(bundle),APP_ID,'stable')
        commit=run('flatpak','info','--show-commit',runtime_ref)
        if commit!=runtime_commit:raise RuntimeError('Runtime changed during the build; rebuild against one installed commit.')
    pinned=json.loads((ROOT/(APP_ID+'.json')).read_text())
    pinned['modules'][0]['sources']=[{'type':'archive','url':'https://github.com/jmlp0818/Forge/releases/download/v'+VERSION+'/'+source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]
    (output/'Forge-GitHub-build.json').write_text(json.dumps(pinned,indent=2)+'\n')
    info={'version':VERSION,'app_id':APP_ID,'runtime_ref':runtime_ref,'runtime_commit':runtime_commit,'architecture':arch,'distribution':'GitHub preview; unsigned bundle, no automatic Forge update repository','source_archive':source.name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'flatpak_version':run('flatpak','--version'),'build_method':'python3 packaging.py build; GNOME Platform used as the pure-Python build environment','source_date_epoch':EPOCH}
    (output/'BUILD-INFO.json').write_text(json.dumps(info,indent=2)+'\n')
    checks=[]
    for item in sorted(output.iterdir()):
        if item.is_file() and item.name!='SHA256SUMS':checks.append(hashlib.sha256(item.read_bytes()).hexdigest()+'  '+item.name)
    (output/'SHA256SUMS').write_text('\n'.join(checks)+'\n')
    print(bundle)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('install','source','build'))
    parser.add_argument('path',type=Path)
    args=parser.parse_args()
    if args.action=='install':install(args.path)
    elif args.action=='source':source_archive(args.path)
    else:build(args.path)
