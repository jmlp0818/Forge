import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET
import forge
import packaging

ROOT=Path(__file__).resolve().parents[1]


class SourceRelease(unittest.TestCase):
    def test_release_identity_is_consistent(self):
        self.assertEqual(forge.APP_ID,packaging.APP_ID)
        self.assertEqual(forge.VERSION,packaging.VERSION)
        manifest=json.loads((ROOT/(forge.APP_ID+'.json')).read_text())
        metadata=ET.parse(ROOT/'data'/(forge.APP_ID+'.metainfo.xml')).getroot()
        self.assertEqual(manifest['app-id'],forge.APP_ID)
        self.assertEqual(metadata.findtext('id'),forge.APP_ID)
        self.assertEqual(metadata.find('releases/release').get('version'),forge.VERSION)
        self.assertIn('python3 packaging.py install /app',manifest['modules'][0]['build-commands'])

    def test_source_archive_is_deterministic_and_contains_build_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            first=Path(folder)/'first.tar.gz';second=Path(folder)/'second.tar.gz'
            packaging.source_archive(first);packaging.source_archive(second)
            self.assertEqual(first.read_bytes(),second.read_bytes())
            with tarfile.open(first) as archive:
                prefix='Forge-'+forge.VERSION+'/'
                names=archive.getnames()
                for relative in ['forge.py','operations.py','packaging.py','LICENSE','tests/test_release.py','data/'+forge.APP_ID+'.desktop','data/'+forge.APP_ID+'.metainfo.xml']:
                    self.assertIn(prefix+relative,names)
                self.assertFalse(any('__pycache__' in name or name.endswith('.env') or '/.git/' in name for name in names))
