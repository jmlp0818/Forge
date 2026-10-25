"""Prepare the installed AppStream catalog required by Flatpak software centers.

This supplements metainfo with the bundle ref, launchable, and cached app icon.
Run after installing Forge's data files, before flatpak build-export.
"""
from pathlib import Path
import gzip
import platform
import shutil
import sys
import xml.etree.ElementTree as ET

APP_ID = 'io.github.jmlp0818.Forge'

def prepare(prefix, arch=None):
    prefix = Path(prefix)
    arch = arch or {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine(), platform.machine())
    component = ET.parse(prefix / 'share/metainfo' / (APP_ID + '.metainfo.xml')).getroot()
    if component.findtext('id') != APP_ID or component.find('releases/release') is None:
        raise ValueError('Missing app ID or release metadata')
    ET.SubElement(component, 'bundle', type='flatpak').text = f'app/{APP_ID}/{arch}/stable'
    ET.SubElement(component, 'icon', type='cached', width='128', height='128').text = APP_ID + '.png'
    categories = ET.SubElement(component, 'categories')
    for category in ('Settings', 'PackageManager'):
        ET.SubElement(categories, 'category').text = category
    root = ET.Element('components', version='1.0')
    root.append(component)
    output = prefix / 'share/app-info/xmls' / (APP_ID + '.xml.gz')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gzip.compress(ET.tostring(root, encoding='utf-8', xml_declaration=True), mtime=0))
    icons = prefix / 'share/app-info/icons/flatpak/128x128'
    icons.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(prefix / 'share/icons/hicolor/128x128/apps' / (APP_ID + '.png'), icons / (APP_ID + '.png'))
    return output

if __name__ == '__main__':
    prepare(sys.argv[1])
