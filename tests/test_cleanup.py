from pathlib import Path
import os
import tempfile
import time
import unittest
import cleanup_host as cleaner

class CleanupSafety(unittest.TestCase):
    def old_file(self,path,days=40):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text('example')
        when=time.time()-days*86400;os.utime(path,(when,when));return path
    def test_category_age_rules_keep_recent_reports_and_current_logs(self):
        self.assertIsNone(cleaner.classify('crash.dmp','cache',8*86400))
        self.assertIsNone(cleaner.classify('app.log.1','cache',8*86400))
        self.assertIsNone(cleaner.classify('current.log','cache',80*86400))
        self.assertEqual(cleaner.classify('app.log.1','cache',40*86400),'app_logs')
        self.assertEqual(cleaner.classify('cache.bin','cache',8*86400),'app_cache')
    def test_recent_crash_metadata_is_not_treated_as_generic_cache(self):
        self.assertIsNone(cleaner.classify_path('browser/Crashpad/metadata','cache',8*86400))
        self.assertEqual(cleaner.classify_path('browser/Crashpad/metadata','cache',40*86400),'crash_reports')
    def test_current_files_in_log_folders_are_preserved(self):
        self.assertIsNone(cleaner.classify_path('app/logs/current.txt','cache',40*86400))
        self.assertEqual(cleaner.classify_path('app/logs/debug.log.1','cache',40*86400),'app_logs')
    def test_unchanged_previewed_cache_file_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);file=self.old_file(home/'.cache/example.bin')
            items,errors=cleaner.snapshot(home/'.cache','cache',time.time())
            self.assertEqual(len(items),1)
            result=cleaner.clean(items,home)
            self.assertEqual(result['removed'],1);self.assertFalse(file.exists())
    def test_changed_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);file=self.old_file(home/'.cache/example.bin')
            items,_=cleaner.snapshot(home/'.cache','cache',time.time())
            file.write_text('new data after preview')
            result=cleaner.clean(items,home)
            self.assertEqual(result['removed'],0);self.assertTrue(file.exists())
    def test_same_size_change_with_restored_modification_time_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);file=self.old_file(home/'.cache/example.bin')
            items,_=cleaner.snapshot(home/'.cache','cache',time.time())
            previous=file.stat()
            file.write_text('changed')
            os.utime(file,ns=(previous.st_atime_ns,previous.st_mtime_ns))
            result=cleaner.clean(items,home)
            self.assertEqual(result['removed'],0);self.assertTrue(file.exists())
    def test_symlinked_ancestor_of_cleanup_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);outside=home/'Documents'
            target=self.old_file(outside/'share/Trash/files/personal.txt')
            (home/'.local').symlink_to(outside,target_is_directory=True)
            items,_=cleaner.snapshot(home/'.local/share/Trash/files','trash',time.time())
            self.assertEqual(len(items),1)
            result=cleaner.clean(items,home)
            self.assertEqual(result['removed'],0);self.assertTrue(target.exists())
    def test_file_added_after_preview_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);trash=home/'.local/share/Trash/files'
            self.old_file(trash/'reviewed.txt')
            items,_=cleaner.snapshot(trash,'trash',time.time())
            added=self.old_file(trash/'new.txt')
            result=cleaner.clean(items,home)
            self.assertEqual(result['removed'],1);self.assertTrue(added.exists())
    def test_symlinks_do_not_delete_their_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);outside=self.old_file(home/'Documents/personal.txt')
            file=self.old_file(home/'.cache/example.bin')
            items,_=cleaner.snapshot(home/'.cache','cache',time.time())
            file.unlink();file.symlink_to(outside)
            result=cleaner.clean(items,home)
            self.assertEqual(result['removed'],0);self.assertTrue(outside.exists())
    def test_directory_replaced_by_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);file=self.old_file(home/'.cache/nested/example.bin')
            items,_=cleaner.snapshot(home/'.cache','cache',time.time())
            file.unlink();file.parent.rmdir()
            outside=home/'Documents';outside.mkdir();target=self.old_file(outside/'example.bin')
            file.parent.symlink_to(outside,target_is_directory=True)
            result=cleaner.clean(items,home)
            self.assertEqual(result['removed'],0);self.assertTrue(target.exists())
    def test_forged_paths_cannot_escape_approved_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);self.old_file(home/'.cache/example.bin')
            outside=self.old_file(home/'Documents/personal.txt')
            items,_=cleaner.snapshot(home/'.cache','cache',time.time())
            items[0]['path']='../Documents/personal.txt'
            self.assertEqual(cleaner.clean(items,home)['removed'],0)
            self.assertTrue(outside.exists())
    def test_trash_subdirectories_and_links_are_removed_without_following_links(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);trash=home/'.local/share/Trash/files'
            file=self.old_file(trash/'old-folder/file.txt')
            outside=self.old_file(home/'Documents/personal.txt')
            (trash/'link').symlink_to(outside)
            items,_=cleaner.snapshot(trash,'trash',time.time())
            result=cleaner.clean(items,home)
            self.assertGreater(result['removed'],0)
            self.assertEqual(list(trash.iterdir()),[])
            self.assertTrue(outside.exists())
    def test_system_commands_are_fixed_and_keep_arch_versions(self):
        self.assertEqual(cleaner.maintenance_command('package_cache','arch'),['/usr/bin/pkexec','/usr/bin/paccache','-r','-k','3'])
        self.assertEqual(cleaner.maintenance_command('system_logs','ubuntu')[-1],'--vacuum-time=30d')
        self.assertIn('clean',cleaner.maintenance_command('package_cache','ubuntu'))
        with self.assertRaises(ValueError):cleaner.maintenance_command('remove-everything','fedora')
        with self.assertRaises(ValueError):cleaner.maintenance_command('package_cache','other')
