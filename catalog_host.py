"""Read configured Flathub catalog metadata and publisher artwork, without app changes."""
import base64
import gzip
import json
from pathlib import Path
import platform
import pwd
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ALLOWED_HOSTS={'dl.flathub.org','flathub.org'}

def allowed_url(url):
    try:
        parsed=urllib.parse.urlsplit(url)
        return parsed.scheme=='https' and parsed.hostname in ALLOWED_HOSTS and not parsed.username and not parsed.password and parsed.port in (None,443)
    except ValueError:return False

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed_url(newurl):raise ValueError('Artwork redirect is outside Flathub.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(url):
    if not allowed_url(url):return None
    try:
        opener=urllib.request.build_opener(SafeRedirect())
        with opener.open(urllib.request.Request(url,headers={'User-Agent':'Forge-AppCatalog/0.13'}),timeout=12) as response:
            data=response.read(5_000_001)
        if len(data)>5_000_000:return None
        if not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8') or data.startswith(b'\xff\x0a') or data[4:12]==b'JXL \r\n\x87\n' or (data.startswith(b'RIFF') and data[8:12]==b'WEBP')):return None
        return base64.b64encode(data).decode('ascii')
    except Exception:return None

def catalog(request):
    ids={identifier for identifier in request.get('ids',[]) if isinstance(identifier,str) and len(identifier)<256}
    featured=set(request.get('featured',[]))
    home=Path(pwd.getpwuid(__import__('os').getuid()).pw_dir)
    arch={'arm64':'aarch64','amd64':'x86_64'}.get(platform.machine(),platform.machine())
    roots=[('user',home/'.local/share/flatpak/appstream/flathub'/arch/'active'),('system',Path('/var/lib/flatpak/appstream/flathub')/arch/'active')]
    if request.get('refresh'):
        for scope,root in roots:
            if root.exists():
                try:subprocess.run(['/usr/bin/flatpak','update','--appstream','--noninteractive','--'+scope,'flathub'],capture_output=True,timeout=45)
                except Exception:pass
    records={}
    for scope,root in roots:
        file=next((root/name for name in ['appstream.xml','appstream.xml.gz'] if (root/name).is_file()),None)
        if not file:continue
        stream=gzip.open(file) if file.suffix=='.gz' else file.open('rb')
        try:
            with stream:
                for event,c in ET.iterparse(stream,events=('end',)):
                    if c.tag!='component':continue
                    identifier=c.findtext('id')
                    if identifier not in ids or identifier in records:c.clear();continue
                    def english(tag):
                        return next((n.text or '' for n in c.findall(tag) if not n.get('{http://www.w3.org/XML/1998/namespace}lang')), '')
                    releases=c.findall('releases/release')
                    record={'id':identifier,'name':english('name'),'summary':english('summary'),'version':releases[0].get('version','') if releases else '', 'source':'Flathub '+scope+' catalog'}
                    for icon in sorted(c.findall('icon'),key=lambda i:int(i.get('height','0')),reverse=True):
                        if icon.get('type')=='cached' and icon.text and Path(icon.text).name==icon.text:
                            image=root/'icons'/(icon.get('width','128')+'x'+icon.get('height','128'))/icon.text
                            if image.is_file() and image.stat().st_size<=1_000_000:
                                record['icon']=base64.b64encode(image.read_bytes()).decode('ascii');break
                    if identifier in featured:
                        shots=c.findall('screenshots/screenshot')
                        shots.sort(key=lambda s:s.get('type')!='default')
                        for shot in shots[:1]:
                            images=sorted(shot.findall('image'),key=lambda i:abs(int(i.get('width','900'))-900))
                            for image in images[:2]:
                                data=download(image.text or '')
                                if data:
                                    record['screenshot']=data;record['image_url']=image.text;record['caption']=next((node.text for node in shot.findall('caption') if not node.get('{http://www.w3.org/XML/1998/namespace}lang')),None) or 'Publisher screenshot'
                                    break
                            if record.get('screenshot'):break
                    records[identifier]=record
                    c.clear()
        except (OSError,ET.ParseError):continue
    return {'apps':list(records.values())}

if __name__=='__main__':
    try:print(json.dumps(catalog(json.load(sys.stdin))))
    except Exception as error:print(json.dumps({'error':str(error)}));sys.exit(1)
