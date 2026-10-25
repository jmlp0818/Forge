"""Local interruption markers. Never replay operations automatically."""
import json
import os
from pathlib import Path
import tempfile
import time


class OperationJournal:
    def __init__(self, provider, root=None):
        if provider not in ('native', 'flatpak', 'cleanup', 'setup'):
            raise ValueError('Unknown operation provider')
        base = Path(root) if root else Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'forge'
        self.path = base / (provider + '-operation.json')

    def begin(self, action):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.operation-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'action': action, 'started': int(time.time())}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name): os.unlink(name)

    def finish(self, error=None):
        # Leave failures for explicit review after restart, including partial work.
        if not error:
            try: self.acknowledge()
            except OSError: pass  # A stale marker prompts review; never replay.

    def pending(self):
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {'action': 'unknown operation'}
        except FileNotFoundError: return None
        except (OSError, ValueError): return {'action': 'unreadable operation record'}

    def acknowledge(self):
        self.path.unlink(missing_ok=True)
