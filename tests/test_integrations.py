from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import flatpaks
import startup
import forge

class FlatpakCommands(unittest.TestCase):
    def app(self): return {'id':'org.gimp.GIMP','branch':'stable','arch':'x86_64','remote':'flathub','scope':'user'}
    def test_install_has_explicit_scope_remote_and_full_ref(self):
        args=flatpaks.command('install','user',self.app())
        self.assertIn('--user',args)
        self.assertEqual(args[-2:],['flathub','app/org.gimp.GIMP/x86_64/stable'])
        self.assertNotIn('--no-gpg-verify',args)
        self.assertEqual(args[0],'flatpak')
    def test_partial_update_checks_do_not_imply_everything_is_current(self):
        self.assertIsNone(forge.combined_update_count(0,None))
        self.assertIsNone(forge.combined_update_count(None,0))
        self.assertEqual(forge.combined_update_count(0,0),0)
        self.assertEqual(forge.combined_update_count(None,3),3)
        self.assertEqual(forge.combined_update_count(2,3),5)

    def test_permissions_summary_distinguishes_static_permissions(self):
        result=flatpaks.permissions_summary('[Context]\nshared=network;ipc;\nsockets=wayland;pulseaudio;\nfilesystems=home:ro;\ndevices=dri;')
        self.assertIn('network',result)
        self.assertIn('home:ro',result)
        self.assertIn('Audio service',result)
        self.assertIn('overrides',result)

    def test_removal_preserves_data_and_does_not_remove_other_apps(self):
        args=flatpaks.command('remove','system',self.app())
        self.assertIn('--system',args)
        self.assertNotIn('--all',args)
        self.assertNotIn('--delete-data',args)
        self.assertNotIn('--unused',args)
    def test_untrusted_ids_and_sources_are_rejected(self):
        for value in ['--delete-data','org.gimp.GIMP;touch /tmp/x','../../org.test.App','org.test.App/branch']:
            app=self.app();app['id']=value
            with self.assertRaises(ValueError):flatpaks.command('install','user',app)
        for value in ['--system','evil remote','https://arbitrary.example/repo']:
            app=self.app();app['remote']=value
            with self.assertRaises(ValueError):flatpaks.command('install','user',app)
        with self.assertRaises(ValueError):flatpaks.command('install','custom',self.app())
    def test_search_remains_one_argument_even_with_metacharacters(self):
        query='paint; $(echo hello)'
        args=flatpaks.command('search','user',query=query)
        self.assertEqual(args[-2:],['--',query])
    def test_source_setup_uses_only_known_flathub_endpoint(self):
        args=flatpaks.command('add-flathub')
        self.assertEqual(args[-1],'https://dl.flathub.org/repo/flathub.flatpakrepo')
        self.assertIn('--if-not-exists',args)
        with self.assertRaises(ValueError):flatpaks.command('add-flathub','system')
    def test_parser_keeps_scopes_branches_and_sources(self):
        text='org.gimp.GIMP\tGIMP\tEdit images\t3.0\tstable\tflathub, other\n'
        apps=flatpaks.parse_apps(text,'user',True)
        self.assertEqual(len(apps),2)
        self.assertEqual(apps[1]['remote'],'other')
        self.assertEqual(apps[0]['scope'],'user')
        self.assertFalse(flatpaks.parse_apps('No matches found','user',True))
    def test_runtime_updates_are_not_mistaken_for_apps(self):
        text='runtime/org.gnome.Platform/x86_64/51\torg.gnome.Platform\tGNOME Platform\tShared runtime\t51\t51\tflathub\tx86_64'
        app=flatpaks.parse_apps(text,'system',updates=True)[0]
        self.assertEqual(app['kind'],'runtime')
        args=flatpaks.command('update','system',app)
        self.assertIn('--runtime',args)
        self.assertEqual(args[-1],'runtime/org.gnome.Platform/x86_64/51')
        self.assertNotIn('--app',flatpaks.command('updates','system'))

    def test_installed_bundle_without_origin_is_still_listed(self):
        apps=flatpaks.parse_apps('org.test.App\tTest\tExample\t1\tstable\t\tx86_64','system')
        self.assertEqual(len(apps),1)

class StartupSettings(unittest.TestCase):
    def test_native_startup_changes_only_the_owned_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=startup.Startup(forge.APP_ID,Path(directory)/'Forge App.py')
            other=Path(directory)/'other.desktop';other.write_text('preserve')
            result=[]
            manager.set(True,True,lambda allowed,error:result.append((allowed,error)),native_dir=directory)
            entry=Path(directory)/(forge.APP_ID+'.desktop')
            self.assertTrue(entry.exists())
            self.assertIn('--background',entry.read_text())
            self.assertIn('Forge App.py',entry.read_text())
            manager.set(False,False,lambda allowed,error:result.append((allowed,error)),native_dir=directory)
            self.assertFalse(entry.exists())
            self.assertEqual(other.read_text(),'preserve')
            self.assertEqual(result,[(True,None),(False,None)])
    def test_minimize_falls_back_to_taskbar_without_a_tray_host(self):
        view=Mock()
        view.appearance={'close_action':'tray'};view.tray.available=False
        forge.Forge.minimize_window(view)
        view.win.minimize.assert_called_once()
        view.win.set_visible.assert_not_called()

    def test_preferences_validate_intervals_and_modes(self):
        self.assertEqual(forge.clean_appearance({'check_interval':False})['check_interval'],30)
        self.assertEqual(forge.clean_appearance({'check_interval':0})['check_interval'],0)
        self.assertEqual(forge.clean_appearance({'check_interval':1440})['check_interval'],1440)
        self.assertEqual(forge.clean_appearance({'close_action':'unrecognized'})['close_action'],'quit')
        self.assertEqual(forge.clean_appearance({'tray_background':True})['close_action'],'tray')
        self.assertFalse(forge.clean_appearance({})['launch_at_login'])
        self.assertTrue(forge.clean_appearance({})['check_on_startup'])
    def test_periodic_timer_reconfigured_and_removed(self):
        from unittest.mock import patch
        view=Mock()
        view.check_timer=42;view.appearance={'check_interval':0}
        with patch.object(forge.GLib,'source_remove') as remove:
            forge.Forge.configure_checks(view)
            remove.assert_called_once_with(42)
        self.assertIsNone(view.check_timer)


class FlatpakUpdateQueue(unittest.TestCase):
    def app(self,scope='user',kind='app'):
        return {'id':'org.test.App' if kind=='app' else 'org.test.Platform','name':'Example','summary':'','version':'2','branch':'stable','remote':'flathub','arch':'x86_64','scope':scope,'kind':kind}
    def test_batch_updates_only_explicit_queued_references(self):
        apps=[self.app(),self.app(kind='runtime')]
        args=flatpaks.command('update-many','user',apps)
        self.assertEqual(args[-2:],['app/org.test.App/x86_64/stable','runtime/org.test.Platform/x86_64/stable'])
        self.assertNotIn('--app',args)
        self.assertNotIn('--runtime',args)
        with self.assertRaises(ValueError):flatpaks.command('update-many','user',[])
    def test_enqueue_deduplicates_without_running_package_commands(self):
        from types import SimpleNamespace
        view=SimpleNamespace(locked=False,backend=SimpleNamespace(busy=False),flatpaks=Mock(busy=False),flatpak_queue={},refresh_queue_count=Mock(),navigate=Mock())
        forge.Forge.enqueue_flatpak_updates(view,[self.app(),self.app(),self.app('system'),self.app(kind='runtime')])
        self.assertEqual(len(view.flatpak_queue),3)
        view.flatpaks.run.assert_not_called()
        view.navigate.assert_called_with('Queue')
    def test_update_all_fetches_updates_and_enqueues_without_applying(self):
        from types import SimpleNamespace
        calls=[]
        class Client:
            busy=False
            def run(self,operation,scope,done):
                calls.append((operation,scope))
                done('runtime/org.test.Platform/x86_64/stable\torg.test.Platform\tPlatform\tShared\t2\tstable\tflathub\tx86_64',None)
        view=SimpleNamespace(locked=False,backend=SimpleNamespace(busy=False),flatpaks=Client(),busy_ui=Mock(),enqueue_flatpak_updates=Mock(),message=Mock(),set_status=Mock())
        forge.Forge.queue_flatpak_updates(view,'system')
        self.assertEqual(calls,[('updates','system')])
        apps=view.enqueue_flatpak_updates.call_args.args[0]
        self.assertEqual(apps[0]['kind'],'runtime')
        self.assertEqual(apps[0]['scope'],'system')

if __name__=='__main__':unittest.main()
