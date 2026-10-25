"""Real subprocess transport; simulated failure messages, no package changes."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from gi.repository import GLib
from flatpaks import Flatpaks
from operations import OperationJournal


class FlatpakFailureTransport(unittest.TestCase):
    def invoke(self, script, operation='update-many'):
        with tempfile.TemporaryDirectory() as folder:
            journal=OperationJournal('flatpak',folder)
            client=Flatpaks(journal=journal)
            replies=[];loop=GLib.MainLoop()
            def done(text,error):replies.append((text,error));loop.quit()
            def timeout():replies.append(('', 'TEST TIMEOUT'));loop.quit();return False
            timer=GLib.timeout_add_seconds(5,timeout)
            with patch('flatpaks.command',return_value=[sys.executable,'-c',script]):
                client.run(operation,'user',done,app=[])
            loop.run()
            GLib.source_remove(timer)
            self.assertEqual(len(replies),1)
            self.assertNotEqual(replies[0][1],'TEST TIMEOUT')
            self.assertFalse(client.busy)
            return replies[0],journal.pending()

    def test_authentication_cancellation_is_a_failure_and_is_marked_for_review(self):
        (text,error),pending=self.invoke("import sys; print('Authentication cancelled'); sys.exit(1)")
        self.assertIn('Authentication cancelled',error)
        self.assertIsNotNone(pending)

    def test_network_error_does_not_report_success(self):
        (text,error),pending=self.invoke("import sys; print('Could not resolve remote host'); sys.exit(1)")
        self.assertIn('resolve remote',error)
        self.assertIsNotNone(pending)

    def test_terminated_process_is_not_success(self):
        (text,error),pending=self.invoke("import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
        self.assertIsNotNone(error)
        self.assertIsNotNone(pending)

    def test_successful_process_clears_marker(self):
        (text,error),pending=self.invoke("print('Done')")
        self.assertIsNone(error)
        self.assertEqual(text,'Done')
        self.assertIsNone(pending)

    def test_read_only_failure_does_not_create_operation_record(self):
        (text,error),pending=self.invoke("import sys; sys.exit(1)",'updates')
        self.assertIsNotNone(error)
        self.assertIsNone(pending)
