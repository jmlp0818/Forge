"""Host cleanup helper: fixed locations, preview snapshots, no shell, no root GUI."""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import time

CATEGORIES = ('app_cache','app_logs','crash_reports','trash')

def locations(home):
    home = Path(home)
    result = [('cache', home/'.cache'), ('state', home/'.local/state'), ('trash', home/'.local/share/Trash/files'), ('trash', home/'.local/share/Trash/info')]
    apps = home/'.var/app'
    if apps.is_dir() and not apps.is_symlink():
        for app in apps.iterdir():
            if app.is_dir() and not app.is_symlink(): result.append(('cache',app/'cache'))
    return result

def classify(name, source, age):
    if source=='trash': return 'trash'
    if name.endswith(('.crash','.dmp','.core','.core.gz')): return 'crash_reports' if age>=30*86400 else None
    if re.search(r'(\.log\.[0-9]+(?:\.gz)?|\.log\.old|\.log\.gz)$',name): return 'app_logs' if age>=30*86400 else None
    if source=='cache' and age>=7*86400 and not name.endswith(('.log','.lock')): return 'app_cache'
    return None

def classify_path(relative, source, age):
    path=Path(relative)
    folders={part.lower().replace(' ','') for part in path.parts[:-1]}
    if source!='trash' and folders & {'crash','crashes','crashpad','crashreports','crashreportscompleted'}:
        return 'crash_reports' if age>=30*86400 else None
    if source!='trash' and folders & {'log','logs'}:
        category=classify(path.name,'state',age)
        return category if category=='app_logs' else None
    return classify(path.name,source,age)

def snapshot(root, source, now, limit=30000):
    items=[];errors=[];count=0
    try:
        if root.is_symlink() or not root.is_dir(): return items,errors
        pending=[root]
        while pending:
            directory=pending.pop()
            try:
                entries=list(os.scandir(directory))
            except OSError as error:
                errors.append(str(error));continue
            for entry in entries:
                count+=1
                if count>limit:
                    errors.append('Scan limit reached; results are partial.');return items,errors
                try:
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(entry.path))
                        if source!='trash':continue
                    if not stat.S_ISREG(info.st_mode) and not (source=='trash' and (stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode))): continue
                    category=classify_path(Path(entry.path).relative_to(root),source,now-info.st_mtime)
                    if category:
                        items.append({'category':category,'root':str(root),'path':str(Path(entry.path).relative_to(root)), 'device':info.st_dev,'inode':info.st_ino,'size':info.st_size if stat.S_ISREG(info.st_mode) else 0,'kind':'dir' if stat.S_ISDIR(info.st_mode) else 'link' if stat.S_ISLNK(info.st_mode) else 'file','mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns})
                except OSError as error: errors.append(str(error))
    except OSError as error: errors.append(str(error))
    return items,errors

def distro_family():
    try:
        text=Path('/etc/os-release').read_text().lower()
        if re.search(r'^id(?:_like)?=.*(?:arch|manjaro|cachyos)',text,re.M):return 'arch'
        if re.search(r'^id(?:_like)?=.*(?:ubuntu|debian|linuxmint)',text,re.M):return 'ubuntu'
        if re.search(r'^id(?:_like)?=.*(?:fedora|rhel)',text,re.M):return 'fedora'
    except OSError: pass
    return 'other'

def maintenance_command(action, family):
    if action=='package_cache':
        options={'ubuntu':['/usr/bin/apt-get','clean'], 'fedora':['/usr/bin/dnf','clean','packages'], 'arch':['/usr/bin/paccache','-r','-k','3']}
        command=options.get(family)
        if not command:raise ValueError('Package-cache cleaning is not supported for this distribution.')
    elif action=='system_logs':command=['/usr/bin/journalctl','--vacuum-time=30d']
    else:raise ValueError('Unknown system cleanup action.')
    return ['/usr/bin/pkexec',*command]

def scan(home=None):
    home=Path(home or pwd.getpwuid(os.getuid()).pw_dir)
    items=[];errors=[]
    for source,root in locations(home):
        records,issues=snapshot(root,source,time.time())
        items.extend(records);errors.extend(issues)
    family=distro_family()
    package_roots={'ubuntu':['/var/cache/apt/archives'],'fedora':['/var/cache/dnf','/var/cache/libdnf5'],'arch':['/var/cache/pacman/pkg']}.get(family,[])
    package_size=0;package_partial=False
    for root in package_roots:
        try:
            for directory,folders,files in os.walk(root,followlinks=False,onerror=lambda error:errors.append(str(error))):
                for filename in files:
                    path=Path(directory)/filename
                    if path.is_symlink():continue
                    if filename.endswith(('.deb','.rpm','.pkg.tar.zst','.pkg.tar.xz')):
                        try:package_size+=path.stat().st_size
                        except OSError:package_partial=True
        except OSError:package_partial=True
    protected=[]
    for root in ['/var/crash','/var/lib/systemd/coredump','/var/spool/abrt']:
        if Path(root).exists():protected.append(root)
    filesystem=os.statvfs(home)
    actions={}
    for action in ('package_cache','system_logs'):
        try:
            argv=maintenance_command(action,family)
            actions[action]=all(Path(arg).is_file() for arg in (argv[0],argv[1]))
        except ValueError:actions[action]=False
    return {'items':items,'errors':errors,'free':filesystem.f_bavail*filesystem.f_frsize,'total':filesystem.f_blocks*filesystem.f_frsize,'family':family,'package_size':package_size,'package_partial':package_partial or bool(errors),'protected_crash_locations':protected,'system_actions':actions}

def remove_snapshot(item, allowed_roots):
    root=item.get('root');relative=item.get('path')
    if root not in allowed_roots or not isinstance(relative,str):raise ValueError('Cleanup location is not approved.')
    parts=Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in ('..','.') for p in parts):raise ValueError('Invalid cleanup path.')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    # O_NOFOLLOW on the final component alone does not protect .local/.var
    # ancestors. Open every component relative to an already checked descriptor.
    absolute=Path(root)
    if not absolute.is_absolute():raise ValueError('Cleanup roots must be absolute.')
    descriptor=os.open(absolute.anchor,flags)
    try:
        for part in absolute.parts[1:]:
            child=os.open(part,flags,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        for part in parts[:-1]:
            child=os.open(part,flags,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        current=os.stat(parts[-1],dir_fd=descriptor,follow_symlinks=False)
        if item.get('kind')=='dir' and item.get('category')=='trash':
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=(item['device'],item['inode']):return False
            os.rmdir(parts[-1],dir_fd=descriptor);return True
        if item.get('kind')=='link' and item.get('category')=='trash':
            if not stat.S_ISLNK(current.st_mode) or (current.st_dev,current.st_ino,current.st_mtime_ns)!=(item['device'],item['inode'],item['mtime_ns']):return False
            os.unlink(parts[-1],dir_fd=descriptor);return True
        if not stat.S_ISREG(current.st_mode):return False
        if (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns)!=(item['device'],item['inode'],item['size'],item['mtime_ns']):return False
        if current.st_ctime_ns!=item.get('ctime_ns'):return False
        os.unlink(parts[-1],dir_fd=descriptor)
        return True
    finally:os.close(descriptor)

def clean(selected, home=None):
    home=Path(home or pwd.getpwuid(os.getuid()).pw_dir)
    roots={str(root):source for source,root in locations(home)}
    removed=0;size=0;skipped=0;errors=[]
    for item in sorted(selected,key=lambda item:len(Path(item.get('path','')).parts),reverse=True):
        try:
            if item.get('category') not in CATEGORIES or item.get('root') not in roots:raise ValueError('Unknown cleanup category.')
            source=roots[item['root']]
            info_path=Path(item['path'])
            expected=classify_path(info_path,source,time.time()-item['mtime_ns']/1_000_000_000)
            if expected!=item['category']:raise ValueError('File is not eligible for this cleanup category.')
            if remove_snapshot(item,roots):removed+=1;size+=item['size']
            else:skipped+=1
        except (OSError,ValueError,KeyError,TypeError) as error:skipped+=1;errors.append(str(error))
    return {'removed':removed,'bytes':size,'skipped':skipped,'errors':errors}

def main():
    request=json.load(sys.stdin)
    action=request.get('action')
    if action=='scan':result=scan()
    elif action=='clean':result=clean(request.get('selected',[]))
    elif action in ('package_cache','system_logs'):
        family=distro_family();argv=maintenance_command(action,family)
        if family=='arch' and Path('/var/lib/pacman/db.lck').exists():raise ValueError('Pacman is busy. Finish package operations before cleaning its cache.')
        process=subprocess.run(argv,capture_output=True,text=True,timeout=300)
        if process.returncode:raise RuntimeError(process.stderr or process.stdout or 'The system cleanup command did not complete.')
        result={'message':process.stdout.strip() or 'System cleanup completed.'}
    else:raise ValueError('Unknown cleanup action.')
    print(json.dumps(result))

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'error':str(error)}));sys.exit(1)
