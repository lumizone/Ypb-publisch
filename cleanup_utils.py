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
