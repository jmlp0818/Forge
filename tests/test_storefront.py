from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import json
import tempfile
import unittest
import catalog
import catalog_host
import forge

class StorefrontReliability(unittest.TestCase):
    def test_remote_artwork_is_limited_to_https_flathub(self):
        self.assertTrue(catalog_host.allowed_url('https://dl.flathub.org/media/icon.png'))
        for url in ['http://dl.flathub.org/icon','https://evil.example/icon','https://dl.flathub.org.evil.example/icon','file:///etc/passwd','https://user:password@dl.flathub.org/icon','https://dl.flathub.org:1234/icon','https://dl.flathub.org:bad/icon']:
            self.assertFalse(catalog_host.allowed_url(url),url)
    def test_cached_artwork_cannot_escape_the_cache_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            client=catalog.Catalog.__new__(catalog.Catalog);client.root=Path(directory)
            client.records={'org.test.App':{'icon':'../private.png'}}
            self.assertIsNone(client.image('org.test.App','icon'))
    def test_refresh_without_download_preserves_offline_screenshot(self):
        with tempfile.TemporaryDirectory() as directory:
            client=catalog.Catalog.__new__(catalog.Catalog);client.root=Path(directory);client.busy=False
            client.records={'org.test.App':{'screenshot':'cached.image','version':'1'}}
            (client.root/'cached.image').write_bytes(b'old image')
            class Process:
                def communicate_utf8_async(self,payload,cancel,callback):callback(self,None)
                def communicate_utf8_finish(self,result):return True,json.dumps({'apps':[{'id':'org.test.App','version':'2'}]}),''
                def get_successful(self):return True
            completed=[]
            with patch.object(catalog.Gio.Subprocess,'new',return_value=Process()):
                client.refresh(['org.test.App'],[],completed.append,True)
            self.assertEqual(completed,[None])
            self.assertEqual(client.get('org.test.App')['version'],'2')
            self.assertTrue(client.image('org.test.App','screenshot').exists())
    def test_lost_tray_host_restores_reachable_dock_window(self):
        view=SimpleNamespace(tray=SimpleNamespace(available=False,reason='Tray missing'),background_hold=True,win=Mock(),release=Mock(),set_status=Mock())
        forge.Forge.tray_status_changed(view)
        view.win.present.assert_called_once();view.win.minimize.assert_called_once();view.release.assert_called_once()
        self.assertFalse(view.background_hold)
    def test_one_app_update_action_collects_both_scopes_without_installing(self):
        sample={'id':'org.test.App','scope':'user','kind':'app','arch':'x86_64','branch':'stable'}
        client=Mock(busy=False)
        client.both.side_effect=lambda operation,done:done([sample],[])
        view=SimpleNamespace(locked=False,backend=SimpleNamespace(busy=False),flatpaks=client,cleaner=SimpleNamespace(busy=False),busy_ui=Mock(),set_status=Mock(),message=Mock(),enqueue_flatpak_updates=Mock())
        forge.Forge.queue_all_app_updates(view)
        self.assertEqual(client.both.call_args.args[0],'updates')
        view.enqueue_flatpak_updates.assert_called_once_with([sample])
        client.run.assert_not_called()
