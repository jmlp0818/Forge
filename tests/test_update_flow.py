from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
import forge
import flatpaks
from requirements import install_command

class UpdateFlow(unittest.TestCase):
    def test_flatpak_writes_allow_normal_desktop_authentication(self):
        app={'id':'org.test.App','arch':'x86_64','branch':'stable','remote':'flathub'}
        for operation in ('install','remove','update','update-many'):
            args=flatpaks.command(operation,'system',[app] if operation=='update-many' else app)
            self.assertNotIn('--noninteractive',args)
            self.assertIn('--assumeyes',args)
            self.assertNotIn('sudo',args)
    def test_all_updates_gathers_both_providers_before_changing_queue(self):
        native='editor;2;x86_64;updates'
        app={'id':'org.test.App','name':'Test','scope':'system','arch':'x86_64','branch':'stable'}
        backend=Mock(busy=False);backend.run.side_effect=lambda op,args,done:done([('Package',(2,native,''))],None)
        client=Mock(busy=False);client.both.side_effect=lambda op,done:done([app],[])
        view=SimpleNamespace(locked=False,backend=backend,flatpaks=client,queue={},busy_ui=Mock(),set_status=Mock(),message=Mock(),enqueue_flatpak_updates=Mock())
        forge.Forge.queue_all_updates(view)
        self.assertEqual(view.queue,{native:'UpdatePackages'})
        self.assertEqual(view.available_updates,[native])
        view.enqueue_flatpak_updates.assert_called_once_with([app])
    def test_gather_failure_keeps_existing_queue_without_partial_additions(self):
        backend=Mock(busy=False);backend.run.side_effect=lambda op,args,done:done([('Package',(2,'new;2;x86_64;updates',''))],None)
        client=Mock(busy=False);client.both.side_effect=lambda op,done:done([],['system: unavailable'])
        view=SimpleNamespace(locked=False,backend=backend,flatpaks=client,queue={'old;1;x86_64;updates':'UpdatePackages'},busy_ui=Mock(),set_status=Mock(),message=Mock(),enqueue_flatpak_updates=Mock())
        forge.Forge.queue_all_updates(view)
        self.assertEqual(len(view.queue),1);view.enqueue_flatpak_updates.assert_not_called();view.message.assert_called_once()
    def test_discover_queries_full_system_catalog_automatically(self):
        backend=Mock();backend.run.side_effect=lambda op,args,done:done([('Package',(2,'x;2;x86_64;updates','Example'))],None)
        view=SimpleNamespace(discovery_view=Mock(return_value=True),app_idea_row=Mock(),note=Mock(),generation=7,busy_ui=Mock(),backend=backend,package_row=Mock(),set_status=Mock(),navigate=Mock())
        forge.Forge.show_catalog_search(view,'example')
        self.assertEqual(backend.run.call_args.args[:2][0],'SearchDetails')
        self.assertEqual(backend.run.call_args.args[1].unpack(),(0,['example']))
        view.package_row.assert_called_once_with('x;2;x86_64;updates','Example',False)
    def test_requirement_install_only_uses_fixed_packages_and_no_partial_arch_refresh(self):
        self.assertEqual(install_command('fedora',['packagekit','python']),['pkexec','dnf','install','--assumeyes','PackageKit','python3'])
        self.assertEqual(install_command('ubuntu',['packagekit']),['pkexec','apt-get','install','--yes','packagekit'])
        self.assertNotIn('-Sy',install_command('arch',['packagekit']))
        for family,missing in [('other',['packagekit']),('fedora',['arbitrary; command'])]:
            with self.assertRaises(ValueError):install_command(family,missing)
    def test_native_auth_hint_supports_new_dictionary_signature_and_background_mode(self):
        calls=[]
        class Bus:
            def call(self,*args):calls.append(args);args[-1](self,args[3],None)
            def call_finish(self,method):
                if method=='CreateTransaction':return forge.GLib.Variant('(o)',('/test',))
                if method=='Introspect':return forge.GLib.Variant('(s)',('<node><interface name="org.freedesktop.PackageKit.Transaction"><method name="SetHints"><arg direction="in" type="a{sv}"/></method></interface></node>',))
            def signal_subscribe(self,*args):return 1
        bus=Bus();backend=forge.Backend(Mock(),interactive=False)
        with patch.object(forge.Gio,'bus_get',side_effect=lambda kind,cancel,cb:cb(None,None)),patch.object(forge.Gio,'bus_get_finish',return_value=bus):
            backend.run('GetUpdates',forge.GLib.Variant('(t)',(0,)),Mock())
        hints=next(call for call in calls if call[3]=='SetHints')
        self.assertEqual(hints[4].unpack(),({'interactive':False},))
        self.assertEqual(calls[-1][6],forge.Gio.DBusCallFlags.NONE)
