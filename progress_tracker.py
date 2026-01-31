"""Progress tracker with automatic cleanup to prevent memory leaks."""

from collections import OrderedDict
from datetime import datetime, timedelta
import threading
import logging

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Thread-safe progress tracker with automatic cleanup."""
    
    def __init__(self, max_entries=100, expire_minutes=30):
        """
        Initialize progress tracker.
        
        Args:
            max_entries: Maximum number of entries to keep (LRU)
            expire_minutes: Minutes after which entries expire
        """
        self.progress = OrderedDict()
        self.timestamps = {}
        self.max_entries = max_entries
        self.expire_minutes = expire_minutes
        self.lock = threading.Lock()
    
    def set(self, job_id, data):
        """Set progress for a job."""
        with self.lock:
            self._cleanup()
            self.progress[job_id] = data
            self.timestamps[job_id] = datetime.now()
            logger.debug(f"Progress updated for {job_id}: {data.get('current', 0)}/{data.get('total', 0)}")
    
    def get(self, job_id, default=None):
        """Get progress for a job."""
        with self.lock:
            self._cleanup()
            return self.progress.get(job_id, default)
    
    def delete(self, job_id):
        """Manually delete a job's progress."""
        with self.lock:
            if job_id in self.progress:
                del self.progress[job_id]
            if job_id in self.timestamps:
                del self.timestamps[job_id]
            logger.debug(f"Progress deleted for {job_id}")
    
    def _cleanup(self):
        """Clean up expired and excess entries."""
        now = datetime.now()
        
        # Remove expired entries
        expired = [
            jid for jid, ts in self.timestamps.items()
            if (now - ts).total_seconds() > self.expire_minutes * 60
        ]
        for jid in expired:
            del self.progress[jid]
            del self.timestamps[jid]
            logger.info(f"Cleaned up expired progress for job {jid}")
        
        # Remove oldest entries if too many
        while len(self.progress) > self.max_entries:
            jid = next(iter(self.progress))
            del self.progress[jid]
            del self.timestamps[jid]
            logger.info(f"Cleaned up oldest progress for job {jid} (LRU)")
    
    def cleanup_all(self):
        """Clean up all entries (for shutdown)."""
        with self.lock:
            count = len(self.progress)
            self.progress.clear()
            self.timestamps.clear()
            logger.info(f"Cleaned up all {count} progress entries")
    
    def __contains__(self, job_id):
        """Check if job_id exists."""
        with self.lock:
            return job_id in self.progress
