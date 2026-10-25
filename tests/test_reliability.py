from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import forge
from operations import OperationJournal


class InterruptionRecovery(unittest.TestCase):
    def test_marker_survives_restart_and_never_contains_a_replay_command(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=OperationJournal('flatpak',folder)
            journal.begin('update-many')
            restarted=OperationJournal('flatpak',folder)
            self.assertEqual(set(restarted.pending()),{'action','started'})
            self.assertEqual(restarted.pending()['action'],'update-many')
            restarted.finish('download interrupted')
            self.assertIsNotNone(restarted.pending())
            restarted.acknowledge()
            self.assertIsNone(journal.pending())

    def test_success_clears_marker_and_corrupt_marker_requests_review(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=OperationJournal('cleanup',folder)
            journal.begin('clean');journal.finish()
            self.assertIsNone(journal.pending())
            journal.path.write_text('broken json')
            self.assertIsNotNone(journal.pending())

    def test_service_restart_finishes_once_and_ignores_late_finished_signal(self):
        class Bus:
            def __init__(self): self.signals={};self.unsubscribed=[]
            def call(self,*args):args[-1](self,args[3],None)
            def call_finish(self,method):
                if method=='CreateTransaction':return forge.GLib.Variant('(o)',('/test',))
                if method=='Introspect':return forge.GLib.Variant('(s)', ('<node><interface name="org.freedesktop.PackageKit.Transaction"><method name="SetHints"><arg direction="in" type="as"/></method></interface></node>',))
            def signal_subscribe(self,*args):
                key=len(self.signals)+1;self.signals[key]=(args[2],args[-1]);return key
            def signal_unsubscribe(self,key):self.unsubscribed.append(key)
        with tempfile.TemporaryDirectory() as folder:
            bus=Bus();done=Mock();journal=OperationJournal('native',folder)
            backend=forge.Backend(Mock(),journal=journal)
            with patch.object(forge.Gio,'bus_get',side_effect=lambda kind,cancel,cb:cb(None,None)),patch.object(forge.Gio,'bus_get_finish',return_value=bus):
                backend.run('UpdatePackages',forge.transaction_args('UpdatePackages',['editor;2;x86_64;updates']),done)
            owner=next(callback for name,callback in bus.signals.values() if name=='NameOwnerChanged')
            tx=next(callback for name,callback in bus.signals.values() if name is None)
            owner(bus,'','','','NameOwnerChanged',forge.GLib.Variant('(sss)',(forge.SERVICE,':1.2',':1.3')))
            tx(bus,'','','','Finished',forge.GLib.Variant('(uu)',(1,0)))
            done.assert_called_once()
            self.assertIn('restarted',done.call_args.args[1])
            self.assertFalse(backend.busy)
            self.assertEqual(set(bus.unsubscribed),set(bus.signals))
            self.assertIsNotNone(journal.pending())

    def test_simulation_does_not_create_an_interruption_marker(self):
        journal=Mock();backend=forge.Backend(Mock(),journal=journal)
        with patch.object(forge.Gio,'bus_get'):
            backend.run('RemovePackages',forge.transaction_args('RemovePackages',['editor;2;x86_64;updates'],True),Mock())
        journal.begin.assert_not_called()
