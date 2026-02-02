"""Utility functions for cleaning up temporary files."""

import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def cleanup_old_files(directory: Path, hours: int = 24, pattern: str = "*", dry_run: bool = False) -> int:
    """
    Clean up files older than specified hours.
    
    Args:
        directory: Directory to clean
        hours: Age threshold in hours
        pattern: Glob pattern for files (default: all files)
        dry_run: If True, only log what would be deleted
        
    Returns:
        Number of files deleted
    """
    if not directory.exists():
        logger.warning(f"Directory does not exist: {directory}")
        return 0
    
    now = time.time()
    cutoff = now - (hours * 3600)
    deleted_count = 0
    total_size = 0
    
    try:
        for file_path in directory.rglob(pattern):
            if file_path.is_file():
                try:
                    file_age = file_path.stat().st_mtime
                    if file_age < cutoff:
                        file_size = file_path.stat().st_size
                        
                        if dry_run:
                            logger.info(f"[DRY RUN] Would delete: {file_path} ({file_size} bytes)")
                        else:
                            file_path.unlink()
                            deleted_count += 1
                            total_size += file_size
                            logger.debug(f"Deleted old file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
        
        if not dry_run and deleted_count > 0:
            logger.info(f"Cleanup complete: deleted {deleted_count} files ({total_size / 1024 / 1024:.2f} MB) from {directory}")
        elif dry_run:
            logger.info(f"[DRY RUN] Would delete {deleted_count} files from {directory}")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error during cleanup of {directory}: {e}")
        return 0


def cleanup_job_files(job_id: str, directories: list) -> bool:
    """
    Clean up all files related to a specific job.
    
    Args:
        job_id: Job ID to clean up
        directories: List of directories to search
        
    Returns:
        True if successful
    """
    deleted_count = 0
    
    for directory in directories:
        if not isinstance(directory, Path):
            directory = Path(directory)
        
        if not directory.exists():
            continue
        
        # Search for files with job_id in name
        try:
            for file_path in directory.glob(f"*{job_id}*"):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        logger.debug(f"Deleted job file: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to delete job file {file_path}: {e}")
        except Exception as e:
            logger.warning(f"Error searching for job files in {directory}: {e}")
    
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} files for job {job_id}")
    
    return deleted_count > 0


def cleanup_empty_dirs(directory: Path, dry_run: bool = False) -> int:
    """
    Remove empty directories (excluding the root directory itself).

    Args:
        directory: Root directory to clean
        dry_run: If True, only log what would be deleted

    Returns:
        Number of directories deleted
    """
    if not directory.exists():
        return 0

    deleted_count = 0

    # Walk bottom-up so we can delete nested empty dirs
    all_dirs = sorted(directory.rglob('*'), key=lambda p: len(p.parts), reverse=True)

    for dir_path in all_dirs:
        if dir_path.is_dir():
            try:
                # Check if directory is empty
                if not any(dir_path.iterdir()):
                    if dry_run:
                        logger.info(f"[DRY RUN] Would delete empty dir: {dir_path}")
                    else:
                        dir_path.rmdir()
                        deleted_count += 1
                        logger.debug(f"Deleted empty directory: {dir_path}")
            except Exception as e:
                logger.warning(f"Failed to delete empty dir {dir_path}: {e}")

    if deleted_count > 0 and not dry_run:
        logger.info(f"Deleted {deleted_count} empty directories from {directory}")

    return deleted_count


def get_directory_size(directory: Path) -> tuple:
    """
    Get total size and file count of a directory.
    
    Returns:
        Tuple of (file_count, total_size_bytes)
    """
    if not directory.exists():
        return (0, 0)
    
    file_count = 0
    total_size = 0
    
    try:
        for file_path in directory.rglob('*'):
            if file_path.is_file():
                file_count += 1
                total_size += file_path.stat().st_size
    except Exception as e:
        logger.warning(f"Error calculating directory size for {directory}: {e}")
    
    return (file_count, total_size)


def cleanup_by_size_limit(directory: Path, max_size_gb: float = 5.0, target_size_gb: float = 4.0) -> int:
    """
    Enforce size limit on a directory by deleting oldest files first (FIFO).

    Args:
        directory: Directory to enforce limit on
        max_size_gb: Maximum allowed size in GB (triggers cleanup)
        target_size_gb: Target size after cleanup in GB

    Returns:
        Number of files deleted
    """
    if not directory.exists():
        return 0

    max_size_bytes = max_size_gb * 1024 * 1024 * 1024
    target_size_bytes = target_size_gb * 1024 * 1024 * 1024

    # Get current size
    file_count, current_size = get_directory_size(directory)

    if current_size <= max_size_bytes:
        logger.debug(f"Directory {directory} is within limit: {current_size / 1024 / 1024 / 1024:.2f} GB / {max_size_gb} GB")
        return 0

    logger.info(f"Directory {directory} exceeds limit: {current_size / 1024 / 1024 / 1024:.2f} GB > {max_size_gb} GB, cleaning up...")

    # Get all files sorted by modification time (oldest first)
    files_with_mtime = []
    try:
        for file_path in directory.rglob('*'):
            if file_path.is_file():
                try:
                    stat = file_path.stat()
                    files_with_mtime.append((file_path, stat.st_mtime, stat.st_size))
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Error listing files in {directory}: {e}")
        return 0

    # Sort by mtime (oldest first)
    files_with_mtime.sort(key=lambda x: x[1])

    deleted_count = 0
    deleted_size = 0

    for file_path, mtime, size in files_with_mtime:
        if current_size - deleted_size <= target_size_bytes:
            break

        try:
            file_path.unlink()
            deleted_count += 1
            deleted_size += size
            logger.debug(f"Deleted old file: {file_path} ({size / 1024 / 1024:.2f} MB)")
        except Exception as e:
            logger.warning(f"Failed to delete {file_path}: {e}")

    # Clean up empty directories
    cleanup_empty_dirs(directory)

    logger.info(f"Size cleanup complete: deleted {deleted_count} files, freed {deleted_size / 1024 / 1024 / 1024:.2f} GB from {directory}")

    return deleted_count


def start_background_cleanup_scheduler(temp_dir: Path, output_dir: Path, archive_dir: Path = None):
    """
    Start background cleanup scheduler with different intervals for different directories.

    Schedule:
    - Temp files: TTL=1 hour, check every 10 minutes
    - Output files: TTL=24 hours, check every 10 minutes
    - Archive: 5GB limit (FIFO), check every 1 hour

    Args:
        temp_dir: Temp directory path
        output_dir: Output directory path
        archive_dir: Archive directory path (optional, uses output_dir if None)
    """
    import threading

    if archive_dir is None:
        archive_dir = output_dir

    def cleanup_temp_and_output():
        """Run every 10 minutes for temp and output."""
        while True:
            try:
                time.sleep(600)  # 10 minutes

                # Temp files: TTL = 1 hour
                deleted_temp = cleanup_old_files(temp_dir, hours=1)
                cleanup_empty_dirs(temp_dir)

                # Output files: TTL = 24 hours
                deleted_output = cleanup_old_files(output_dir, hours=24)
                cleanup_empty_dirs(output_dir)

                if deleted_temp > 0 or deleted_output > 0:
                    logger.info(f"[Scheduled cleanup] Temp: {deleted_temp} files, Output: {deleted_output} files")

            except Exception as e:
                logger.error(f"Error in scheduled cleanup (temp/output): {e}")

    def cleanup_archive_size():
        """Run every 1 hour for archive size limit."""
        while True:
            try:
                time.sleep(3600)  # 1 hour

                # Archive: 5GB limit, target 4GB after cleanup
                deleted = cleanup_by_size_limit(archive_dir, max_size_gb=5.0, target_size_gb=4.0)

                if deleted > 0:
                    logger.info(f"[Scheduled cleanup] Archive: {deleted} files deleted (size limit)")

            except Exception as e:
                logger.error(f"Error in scheduled cleanup (archive): {e}")

    # Start background threads
    temp_output_thread = threading.Thread(target=cleanup_temp_and_output, daemon=True, name="cleanup-temp-output")
    archive_thread = threading.Thread(target=cleanup_archive_size, daemon=True, name="cleanup-archive")

    temp_output_thread.start()
    archive_thread.start()

    logger.info("Background cleanup scheduler started:")
    logger.info("  - Temp (TTL=1h) + Output (TTL=24h): every 10 minutes")
    logger.info("  - Archive (max 5GB): every 1 hour")


def auto_cleanup_startup(temp_dir: Path, output_dir: Path, uploads_dir: Path, hours: int = 24) -> None:
    """
    Run cleanup on application startup.
    
    Args:
        temp_dir: Temp directory path
        output_dir: Output directory path
        uploads_dir: Uploads directory path
        hours: Age threshold in hours
    """
    logger.info("Running startup cleanup...")
    
    # Log directory sizes before cleanup
    temp_count, temp_size = get_directory_size(temp_dir)
    output_count, output_size = get_directory_size(output_dir)
    uploads_count, uploads_size = get_directory_size(uploads_dir)
    
    logger.info(f"Before cleanup - temp: {temp_count} files ({temp_size / 1024 / 1024:.2f} MB)")
    logger.info(f"Before cleanup - output: {output_count} files ({output_size / 1024 / 1024:.2f} MB)")
    logger.info(f"Before cleanup - uploads: {uploads_count} files ({uploads_size / 1024 / 1024:.2f} MB)")
    
    # Run cleanup - files first, then empty directories
    cleanup_old_files(temp_dir, hours=hours)
    cleanup_old_files(output_dir, hours=hours)
    cleanup_old_files(uploads_dir, hours=hours)

    # Clean up empty directories
    cleanup_empty_dirs(temp_dir)
    cleanup_empty_dirs(output_dir)
    cleanup_empty_dirs(uploads_dir)
    
    # Log after cleanup
    temp_count_after, temp_size_after = get_directory_size(temp_dir)
    output_count_after, output_size_after = get_directory_size(output_dir)
    uploads_count_after, uploads_size_after = get_directory_size(uploads_dir)
    
    total_deleted = (temp_count - temp_count_after) + (output_count - output_count_after) + (uploads_count - uploads_count_after)
    total_freed = (temp_size - temp_size_after) + (output_size - output_size_after) + (uploads_size - uploads_size_after)
    
    logger.info(f"Startup cleanup complete: deleted {total_deleted} files, freed {total_freed / 1024 / 1024:.2f} MB")
