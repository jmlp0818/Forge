"""Regression gate for metadata missing from early hand-exported installers."""
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from prepare_appstream import APP_ID,prepare

class InstallerMetadata(unittest.TestCase):
    def test_installer_contains_release_identity_bundle_and_icon(self):
        source=Path(__file__).resolve().parents[1]
        manifest=json.loads((source/(APP_ID+'.json')).read_text())
        self.assertIn('python3 prepare_appstream.py /app',manifest['modules'][0]['build-commands'])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for filename,folder in [(APP_ID+'.metainfo.xml','metainfo'),(APP_ID+'.png','icons/hicolor/128x128/apps')]:
                target=root/'share'/folder/filename;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source/'data'/filename,target)
            collection=ET.fromstring(gzip.decompress(prepare(root,'x86_64').read_bytes()))
            item=collection.find('component')
            original=ET.parse(source/'data'/(APP_ID+'.metainfo.xml')).getroot()
            self.assertEqual(item.findtext('name'),'Forge')
            self.assertEqual(item.find('releases/release').get('version'),original.find('releases/release').get('version'))
            self.assertEqual(item.findtext('bundle'),f'app/{APP_ID}/x86_64/stable')
            self.assertEqual(item.findtext('launchable'),APP_ID+'.desktop')
            self.assertTrue((root/'share/app-info/icons/flatpak/128x128'/item.findtext('icon')).is_file())
