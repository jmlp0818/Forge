import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import forge

ROOT = Path(__file__).resolve().parents[1]

class Contracts(unittest.TestCase):
    def test_package_id(self):
        self.assertEqual(forge.package_parts('git;2.0;x86_64;fedora'), ['git','2.0','x86_64','fedora'])
        self.assertEqual(len(forge.package_parts('git')), 4)

    def test_simulation_and_execution(self):
        ids = ['git;2.0;x86_64;fedora']
        for method in ['InstallPackages', 'UpdatePackages', 'RemovePackages']:
            planned = forge.transaction_args(method, ids, True)
            applied = forge.transaction_args(method, ids)
            self.assertEqual(planned.unpack()[0], 6)
            self.assertEqual(applied.unpack()[0], 2)
            self.assertEqual(planned.unpack()[1:], applied.unpack()[1:])
            self.assertEqual(applied.get_type_string(), '(tasbb)' if method == 'RemovePackages' else '(tas)')
        self.assertEqual(forge.transaction_args('RemovePackages', ids).unpack()[2:], (False,False))

    def test_flags_match_packagekit(self):
        gi = forge.gi
        try:
            gi.require_version('PackageKitGlib', '1.0')
        except ValueError:
            self.skipTest('PackageKit introspection not installed')
        from gi.repository import PackageKitGlib as P
        self.assertEqual(forge.transaction_args('InstallPackages', ['git'], True).unpack()[0],
                         (1 << int(P.TransactionFlagEnum.ONLY_TRUSTED)) | (1 << int(P.TransactionFlagEnum.SIMULATE)))

    def test_flatpak_metadata(self):
        manifest = json.loads((ROOT / 'io.github.jmlp0818.Forge.json').read_text())
        app_id = manifest['app-id']
        self.assertEqual(app_id, forge.APP_ID)
        self.assertIn('--system-talk-name=org.freedesktop.PackageKit', manifest['finish-args'])
        self.assertFalse(any('host' in arg or 'filesystem' in arg for arg in manifest['finish-args']))
        tree = ET.parse(ROOT / 'data' / f'{app_id}.metainfo.xml')
        self.assertEqual(tree.findtext('id'), app_id)
        self.assertTrue((ROOT / 'data' / f'{app_id}.desktop').exists())


class RepositorySetup(unittest.TestCase):
    def test_first_run_persistence_and_corrupt_state(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            state = forge.SetupState(Path(directory) / 'forge' / 'setup.json')
            self.assertFalse(state.complete())
            state.save()
            self.assertTrue(forge.SetupState(state.path).complete())
            state.path.write_text('{broken')
            self.assertFalse(state.complete())
            state.path.write_text('[]')
            self.assertFalse(state.complete())

    def test_repository_status_does_not_assume_enabled(self):
        repos = {'google-chrome': ('Google Chrome', False), 'fedora': ('Fedora', True)}
        self.assertEqual(forge.repository_state('google-chrome', repos), 'Disabled')
        self.assertEqual(forge.repository_state('fedora', repos), 'Enabled')
        self.assertEqual(forge.repository_state('rpmfusion-free', repos), 'Not configured')

    def test_catalog_links_and_unique_repo_ids(self):
        catalog = forge.REPO_CATALOG
        self.assertEqual(len({r[1] for r in catalog}), len(catalog))
        self.assertTrue(all(r[3].startswith('https://') for r in catalog))
        self.assertIn('rpmfusion-free', {r[1] for r in catalog})
        self.assertIn('rpmfusion-nonfree', {r[1] for r in catalog})

class BackendTransactions(unittest.TestCase):
    def test_repository_enable_waits_for_finished_and_cleans_up(self):
        from unittest.mock import patch
        class FakeBus:
            def __init__(self):
                self.calls = []
                self.unsubscribed = []
            def call(self, *args):
                self.calls.append(args)
                args[-1](self, 'created' if args[3] == 'CreateTransaction' else 'introspection' if args[3]=='Introspect' else 'invoked', None)
            def call_finish(self, result):
                if result=='created':return forge.GLib.Variant('(o)',('/test/transaction',))
                if result=='introspection':return forge.GLib.Variant('(s)',('<node><interface name="org.freedesktop.PackageKit.Transaction"><method name="SetHints"><arg direction="in" type="as"/></method></interface></node>',))
                return None
            def signal_subscribe(self, *args):
                self.callback = args[-1]
                return 12
            def signal_unsubscribe(self, token): self.unsubscribed.append(token)
        bus = FakeBus()
        completed = []
        backend = forge.Backend(lambda text: None)
        with patch.object(forge.Gio, 'bus_get', side_effect=lambda kind, cancel, cb: cb(None, None, None)), patch.object(forge.Gio, 'bus_get_finish', return_value=bus):
            backend.run('RepoEnable', forge.GLib.Variant('(sb)', ('google-chrome', True)), lambda result, error: completed.append((result, error)))
        self.assertTrue(backend.busy)
        self.assertEqual([c[3] for c in bus.calls],['CreateTransaction','Introspect','SetHints','RepoEnable'])
        self.assertEqual(bus.calls[2][4].unpack(),(['interactive=true'],))
        self.assertEqual(bus.calls[3][4].unpack(), ('google-chrome', True))
        self.assertFalse(completed)
        bus.callback(bus, '', '', '', 'Finished', forge.GLib.Variant('(uu)', (1, 1)), None)
        self.assertEqual(completed, [([], None)])
        self.assertFalse(backend.busy)
        self.assertEqual(bus.unsubscribed, [12, 12])

class Discovery(unittest.TestCase):
    def test_collections_have_descriptions_and_known_packages(self):
        self.assertEqual(len(forge.COLLECTIONS), 10)
        for category in forge.COLLECTIONS:
            names = forge.collection_names(category)
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(all(name in forge.DISCOVER_APPS for name in names))
            names.clear()
            self.assertTrue(forge.collection_names(category))
        self.assertTrue(all(name in forge.DISCOVER_APPS for name in forge.FEATURED))

    def test_browse_resolves_exact_names_without_installing(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        view = SimpleNamespace(backend=SimpleNamespace(busy=False), locked=False,
                               heading=Mock(), description=Mock(), search=Mock(), load=Mock())
        forge.Forge.browse_packages(view, ['git', 'meld'], 'Development')
        method, args = view.load.call_args.args
        self.assertEqual(method, 'Resolve')
        self.assertEqual(args.unpack(), (0, ['git', 'meld']))
        view.load.reset_mock()
        view.backend.busy = True
        forge.Forge.browse_packages(view, ['gimp'], 'Creative')
        view.load.assert_not_called()

class TransactionGuardrails(unittest.TestCase):
    def pkg(self, name, info):
        return ('Package', (info, name + ';1;x86_64;fedora', 'summary'))

    def test_requested_core_removal_blocked_before_simulation(self):
        for name in ['systemd', 'kernel-core', 'glibc', 'rpm', 'dnf5', 'grub2-efi-x64', 'NetworkManager']:
            plan = forge.assess_plan('RemovePackages', [name + ';1;x86_64;installed'], [])
            self.assertIn(name, plan['blocked'])

    def test_indirect_core_removal_is_blocked_on_install(self):
        plan = forge.assess_plan('InstallPackages', ['tool;1;x86_64;repo'], [self.pkg('glibc', 13)])
        self.assertEqual(plan['blocked'], ['glibc'])

    def test_desktop_removal_requires_acknowledgment(self):
        plan = forge.assess_plan('RemovePackages', ['gdm;1;x86_64;installed'], [self.pkg('gdm', 13)])
        self.assertTrue(plan['destructive'])
        self.assertFalse(plan['blocked'])
        self.assertTrue(any('sign in' in w for w in plan['warnings']))

    def test_core_updates_are_warned_not_blocked(self):
        plan = forge.assess_plan('UpdatePackages', ['systemd;2;x86_64;updates'], [self.pkg('systemd', 11)])
        self.assertFalse(plan['blocked'])
        self.assertFalse(plan['destructive'])
        self.assertTrue(any('core system' in w for w in plan['warnings']))
        self.assertTrue(plan['lines'][0].startswith('Update'))

    def test_downgrades_require_acknowledgment(self):
        plan = forge.assess_plan('InstallPackages', ['gimp;1;x86_64;repo'], [self.pkg('gimp', 20)])
        self.assertTrue(plan['destructive'])
        self.assertTrue(any('Downgrades' in w for w in plan['warnings']))

    def test_regular_install_does_not_have_removal_warning(self):
        plan = forge.assess_plan('InstallPackages', ['gimp;1;x86_64;repo'], [self.pkg('gimp', 12)])
        self.assertFalse(plan['blocked'])
        self.assertFalse(plan['destructive'])
        self.assertEqual(plan['removed'], [])

class Appearance(unittest.TestCase):
    def test_preferences_round_trip_and_corruption(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = forge.AppearanceSettings(Path(directory) / 'forge' / 'appearance.json')
            self.assertEqual(store.load(), forge.APPEARANCE_DEFAULTS)
            chosen = {**forge.APPEARANCE_DEFAULTS, 'scheme': 'system', 'accent': 'teal', 'compact': True}
            store.save(chosen)
            self.assertEqual(forge.AppearanceSettings(store.path).load(), chosen)
            for content in ['{bad', '[]', '{"accent":[],"scheme":{},"compact":"false"}']:
                store.path.write_text(content)
                self.assertEqual(store.load(), forge.APPEARANCE_DEFAULTS)

    def test_styles_parse_for_all_accent_mode_density_combinations(self):
        errors = []
        provider = forge.Gtk.CssProvider()
        provider.connect('parsing-error', lambda provider, section, error: errors.append(error.message))
        for accent in forge.ACCENT_COLORS:
            for dark in (True, False):
                for compact in (True, False):
                    css = forge.appearance_css({'accent': accent, 'compact': compact}, dark)
                    provider.load_from_data(css.encode())
        self.assertFalse(errors, errors)

    def test_untrusted_preferences_cannot_inject_css(self):
        settings = forge.clean_appearance({'accent': 'red; } * { color: red;', 'scheme': 'invalid', 'compact': 1})
        self.assertEqual(settings, forge.APPEARANCE_DEFAULTS)

class TaskDiscovery(unittest.TestCase):
    def test_plain_language_tasks(self):
        self.assertIn('gimp', forge.catalog_matches('I need an app to edit photos'))
        self.assertIn('calibre', forge.catalog_matches('read ebooks'))
        self.assertIn('obs-studio', forge.catalog_matches('record my screen'))
        self.assertIn('orca', forge.catalog_matches('screen reader'))
        self.assertIn('supertuxkart', forge.catalog_matches('find games'))
        self.assertIn('libreoffice-calc', forge.catalog_matches('Excel alternative'))

    def test_names_rank_first_and_empty_queries_do_not_match_everything(self):
        self.assertEqual(forge.catalog_matches('git')[0], 'git')
        self.assertEqual(forge.catalog_matches('GIMP')[0], 'gimp')
        self.assertEqual(forge.catalog_matches('please find me an app'), [])
        self.assertEqual(forge.catalog_matches('nonexistentuniqueword'), [])
        self.assertEqual(len(forge.catalog_matches('game', limit=2)), 2)

    def test_collections_do_not_install_or_resolve(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        view = SimpleNamespace(discovery_view=Mock(return_value=True), app_idea_row=Mock(), set_status=Mock())
        forge.Forge.show_app_collection(view, ['gimp', 'krita'], 'Creative')
        self.assertEqual(view.app_idea_row.call_count, 2)
        self.assertIn('availability not checked', view.set_status.call_args.args[0])
        view.discovery_view.return_value = False
        view.app_idea_row.reset_mock()
        forge.Forge.show_app_collection(view, ['gimp'], 'Creative')
        view.app_idea_row.assert_not_called()

    def test_all_apps_have_task_metadata(self):
        self.assertEqual(set(forge.TASK_TAGS), set(forge.DISCOVER_APPS))
        self.assertEqual(len(forge.DISCOVER_APPS), 36)

class AppIcons(unittest.TestCase):
    def test_unverified_third_party_artwork_is_not_bundled(self):
        sources = json.loads((ROOT / 'data/app-icons/sources.json').read_text())
        self.assertGreaterEqual(len(sources), 30)
        self.assertEqual(list((ROOT / 'data/app-icons').glob('*.png')), [])
        self.assertIsNone(forge.app_icon_path('gimp'))

    def test_package_names_cannot_escape_asset_directory(self):
        self.assertIsNone(forge.app_icon_path('../forge'))
        self.assertIsNone(forge.app_icon_path('/etc/passwd'))
        self.assertIsNone(forge.app_icon_path('unrecognized-package'))

    def test_icon_lookup_works_in_flatpak_install_location(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'gimp.png').write_bytes(b'test')
            self.assertEqual(forge.app_icon_path('gimp', [root]), root / 'gimp.png')
            self.assertIsNone(forge.app_icon_path('gimp', []))

class DistroSupport(unittest.TestCase):
    def detect(self, content):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'os-release'
            path.write_text(content)
            return forge.host_distribution([path])

    def test_host_families_and_release(self):
        ubuntu = self.detect('ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\nPRETTY_NAME="Ubuntu 24.04 LTS"')
        self.assertEqual(ubuntu['family'], 'ubuntu')
        self.assertEqual(ubuntu['version'], '24.04')
        self.assertEqual(ubuntu['codename'], 'noble')
        self.assertEqual(self.detect('ID=cachyos\nID_LIKE=arch')['family'], 'arch')
        self.assertEqual(self.detect('ID=linuxmint\nID_LIKE="ubuntu debian"')['family'], 'ubuntu')
        self.assertEqual(self.detect('ID=fedora')['family'], 'fedora')
        self.assertEqual(self.detect('ID=opensuse-tumbleweed')['family'], 'other')
        self.assertEqual(forge.host_distribution([])['family'], 'other')

    def test_source_suggestions_do_not_mix_distributions(self):
        arch = str(forge.distro_sources({'family': 'arch'}))
        ubuntu = str(forge.distro_sources({'family': 'ubuntu'}))
        self.assertIn('multilib', arch)
        self.assertNotIn('Fedora', arch)
        self.assertIn('Universe', ubuntu)
        self.assertNotIn('RPM Fusion', ubuntu)

    def test_package_names_map_and_deduplicate_for_arch(self):
        self.assertEqual(forge.native_package_names(['libreoffice-writer', 'libreoffice-calc', 'minetest'], 'arch'), ['libreoffice-fresh', 'luanti'])
        self.assertEqual(forge.native_package_names(['libreoffice-writer'], 'ubuntu'), ['libreoffice-writer'])
        self.assertEqual(forge.native_package_names(['git'], 'other'), ['git'])

    def test_native_core_package_guards_cover_apt_and_pacman(self):
        for name in ['apt', 'dpkg', 'libc6', 'pacman', 'linux-lts', 'linux-image-generic']:
            self.assertTrue(forge.is_core_package(name), name)

class WindowsFriendlyDiscovery(unittest.TestCase):
    def test_familiar_app_groups_reference_available_catalog_entries(self):
        for familiar, purpose, names, caveat in forge.WINDOWS_ALTERNATIVES:
            self.assertTrue(familiar and purpose and caveat)
            self.assertTrue(all(name in forge.DISCOVER_APPS for name in names))

    def test_friendly_rows_keep_source_but_hide_technical_details(self):
        title, summary = forge.package_presentation('gimp', '3.0-test', 'x86_64', 'fedora', 'Edit photos')
        self.assertEqual(title, 'GIMP')
        self.assertIn('fedora', summary)
        self.assertNotIn('x86_64', summary)
        self.assertNotIn('3.0-test', summary)
        title, summary = forge.package_presentation('gimp', '3.0-test', 'x86_64', 'fedora', 'Edit photos', True)
        self.assertIn('x86_64', summary)
        self.assertIn('3.0-test', summary)

    def test_unknown_package_names_are_preserved(self):
        self.assertEqual(forge.package_presentation('lib-example', '1', 'x86_64', '', 'Helper')[0], 'lib-example')
        self.assertFalse(forge.clean_appearance({})['technical_details'])
        self.assertFalse(forge.clean_appearance({'technical_details': 'true'})['technical_details'])

class UpdateExperience(unittest.TestCase):
    def packages(self, version='1'):
        return [('Package', (2, 'gimp;' + version + ';x86_64;updates', 'Image editor'))]

    def test_notifications_are_deduplicated_and_errors_preserve_state(self):
        state = forge.UpdateState()
        self.assertIsNone(state.count)
        self.assertTrue(state.accept(self.packages()))
        self.assertEqual(state.count, 1)
        self.assertFalse(state.accept(self.packages()))
        self.assertFalse(state.accept([], 'Offline'))
        self.assertEqual(state.count, 1)
        self.assertTrue(state.accept(self.packages('2')))
        self.assertFalse(state.accept([]))
        self.assertEqual(state.count, 0)

    def test_restart_advice_uses_service_signal_severity(self):
        self.assertIn('restarting the computer', forge.restart_message([('RequireRestart', (4, 'pkg'))]))
        self.assertIn('signing out', forge.restart_message([('RequireRestart', (3, 'pkg'))]))
        self.assertIn('affected applications', forge.restart_message([('RequireRestart', (2, 'pkg'))]))
        self.assertIn('no restart request', forge.restart_message([('RequireRestart', (1, 'pkg'))]))

    def test_tray_identity_and_raw_icon_format(self):
        import tray
        indicator = tray.Tray.__new__(tray.Tray)
        indicator.app_id = forge.APP_ID
        indicator.count = 0
        self.assertEqual(indicator.icon_name, forge.APP_ID)
        indicator.count = 4
        self.assertEqual(indicator.icon_name, forge.APP_ID + '.Updates')
        pixels = tray.icon_pixmap(ROOT / 'data' / (forge.APP_ID + '.Updates.png'))
        width, height, data = pixels[0]
        self.assertEqual(len(data), width * height * 4)
        self.assertEqual(width, 32)
        forge.Gio.DBusNodeInfo.new_for_xml(tray.ITEM_XML)
        forge.Gio.DBusNodeInfo.new_for_xml(tray.MENU_XML)

    def test_background_is_opt_in_and_notifications_default_on(self):
        settings = forge.clean_appearance({})
        self.assertFalse(settings['tray_background'])
        self.assertTrue(settings['update_notifications'])

if __name__ == '__main__': unittest.main()
