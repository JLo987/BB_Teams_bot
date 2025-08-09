import azure.functions as func
import psycopg
import logging
import os
import json
import sys
import urllib.parse
import asyncio
import time
from typing import List, Dict, Optional
from shared.graph_helper import get_graph_client

# Add parent directory to Python path for relative imports
parent_dir = os.path.dirname(os.path.dirname(__file__))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Now import the functions directly
from extract_text import extract_text_from_onedrive_direct
from embed_function import get_embedding_direct

# Database configuration
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

# Note: No longer need HTTP calls between functions - using direct imports

# OneDrive/SharePoint configuration
GRAPH_SITE_ID = os.getenv("GRAPH_SITE_ID")
GRAPH_DELTA_LINK = os.getenv("GRAPH_DELTA_LINK")
GRAPH_DRIVE_ID = os.getenv("GRAPH_DRIVE_ID")  # Optional: specific drive ID

# Sync configuration
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

# Enhanced sync configuration for enterprise use
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))
INITIAL_RETRY_DELAY = float(os.getenv("INITIAL_RETRY_DELAY", "1.0"))
MAX_RETRY_DELAY = float(os.getenv("MAX_RETRY_DELAY", "60.0"))
RATE_LIMIT_RETRY_DELAY = float(os.getenv("RATE_LIMIT_RETRY_DELAY", "30.0"))

class SyncError(Exception):
    """Base exception for sync operations"""
    pass

class RecoverableError(SyncError):
    """Error that can be retried"""
    pass

class PermanentError(SyncError):
    """Error that should not be retried"""
    pass

def is_rate_limit_error(error: Exception) -> bool:
    """Check if error is due to rate limiting"""
    error_str = str(error).lower()
    return any(phrase in error_str for phrase in [
        'throttled', 'rate limit', 'too many requests', '429', 
        'service unavailable', '503', 'quota exceeded'
    ])

def is_recoverable_error(error: Exception) -> bool:
    """Determine if an error is recoverable and should be retried"""
    error_str = str(error).lower()
    
    # Definitely recoverable
    recoverable_patterns = [
        'timeout', 'connection', 'network', 'temporary', 
        'service unavailable', '503', '502', '504'
    ]
    
    # Definitely not recoverable
    permanent_patterns = [
        'not found', '404', 'unauthorized', '401', 
        'forbidden', '403', 'bad request', '400'
    ]
    
    if any(pattern in error_str for pattern in permanent_patterns):
        return False
    
    if any(pattern in error_str for pattern in recoverable_patterns):
        return True
    
    # Rate limiting is recoverable with longer delay
    if is_rate_limit_error(error):
        return True
    
    # Default to recoverable for unknown errors
    return True

async def retry_with_backoff(func, *args, max_retries=MAX_RETRIES, **kwargs):
    """Execute function with exponential backoff retry logic"""
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if attempt == max_retries:
                # Final attempt failed
                break
            
            if not is_recoverable_error(e):
                # Don't retry permanent errors
                raise PermanentError(f"Permanent error: {str(e)}") from e
            
            # Calculate delay
            if is_rate_limit_error(e):
                delay = RATE_LIMIT_RETRY_DELAY
                logging.warning(f"Rate limit detected, waiting {delay}s before retry {attempt + 1}/{max_retries}")
            else:
                delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                logging.warning(f"Recoverable error on attempt {attempt + 1}/{max_retries}, retrying in {delay}s: {str(e)}")
            
            await asyncio.sleep(delay)
    
    # All retries exhausted
    raise RecoverableError(f"Max retries ({max_retries}) exhausted: {str(last_exception)}") from last_exception

def get_supported_file_types() -> List[str]:
    """Get list of supported file extensions"""
    return ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', 
            '.txt', '.csv', '.jpg', '.jpeg', '.png', '.tif', '.tiff']

def is_supported_file(filename: str) -> bool:
    """Check if file type is supported for text extraction"""
    if not filename:
        return False
    extension = '.' + filename.lower().split('.')[-1] if '.' in filename else ''
    return extension in get_supported_file_types()

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks"""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Try to end at a sentence boundary
        if end < len(text):
            # Look for sentence endings within the last 100 characters
            sentence_end = text.rfind('.', max(start, end - 100), end)
            if sentence_end != -1:
                end = sentence_end + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap
        if start >= len(text):
            break
    
    return chunks

async def extract_text_from_file(drive_id: str, file_id: str, filename: str) -> Optional[str]:
    """Extract text from OneDrive file using the direct extract_text function"""
    logging.info(f"Extracting text directly from file: {filename}")
    
    try:
        text = await extract_text_from_onedrive_direct(drive_id, file_id, filename)
        return text
    except Exception as e:
        logging.error(f"Error extracting text from {filename}: {str(e)}")
        return None

async def get_embedding(text: str) -> Optional[List[float]]:
    """Get embedding for text using the direct embed function"""
    try:
        embedding = get_embedding_direct(text)
        return embedding
    except Exception as e:
        logging.error(f"Error getting embedding: {str(e)}")
        return None

async def extract_and_store_file_permissions(graph_client, drive_id: str, file_id: str, filename: str, cursor):
    """Extract file permissions from OneDrive and store in optimized permissions table"""
    try:
        # Get file permissions from Microsoft Graph
        permissions = await graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(file_id).permissions.get()
        logging.info(f"Permissions: {permissions}")
        
        if not permissions or not hasattr(permissions, 'value'):
            logging.info(f"No permissions found for file: {filename}")
            return
        
        # Delete existing permissions for this file
        cursor.execute("DELETE FROM file_permissions_v2 WHERE file_id = %s", (file_id,))
        
        # Insert new permissions using optimized structure
        for permission in permissions.value:
            try:
                permission_data = {
                    'file_id': file_id,
                    'drive_id': drive_id,
                    'filename': filename,
                    'permission_id': permission.id,
                    'permission_type': getattr(permission, 'type', 'unknown'),
                    'role_name': getattr(permission, 'role', ['unknown'])[0] if hasattr(permission, 'role') and permission.role else 'unknown',
                    'granted_to_user_id': None,
                    'granted_to_user_email': None,
                    'granted_to_group_id': None,
                    'granted_to_group_name': None,
                    'link_type': None,
                    'link_scope': None,
                    'expires_at': None,
                    'is_active': True
                }
                
                # Extract granted_to information
                if hasattr(permission, 'granted_to') and permission.granted_to:
                    if hasattr(permission.granted_to, 'user') and permission.granted_to.user:
                        permission_data['granted_to_user_id'] = getattr(permission.granted_to.user, 'id', None)
                        permission_data['granted_to_user_email'] = getattr(permission.granted_to.user, 'email', None)
                    elif hasattr(permission.granted_to, 'group') and permission.granted_to.group:
                        permission_data['granted_to_group_id'] = getattr(permission.granted_to.group, 'id', None)
                        permission_data['granted_to_group_name'] = getattr(permission.granted_to.group, 'display_name', None)
                
                # Extract link information for sharing links
                if hasattr(permission, 'link') and permission.link:
                    permission_data['link_type'] = getattr(permission.link, 'type', None)
                    permission_data['link_scope'] = getattr(permission.link, 'scope', None)
                
                # Extract expiration
                if hasattr(permission, 'expiration_date_time') and permission.expiration_date_time:
                    permission_data['expires_at'] = permission.expiration_date_time.isoformat()
                
                # Insert permission record
                cursor.execute("""
                    INSERT INTO file_permissions_v2 (
                        file_id, drive_id, filename, permission_id, permission_type,
                        role_name, granted_to_user_id, granted_to_user_email,
                        granted_to_group_id, granted_to_group_name, link_type,
                        link_scope, expires_at, is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    permission_data['file_id'], permission_data['drive_id'], permission_data['filename'],
                    permission_data['permission_id'], permission_data['permission_type'], permission_data['role_name'],
                    permission_data['granted_to_user_id'], permission_data['granted_to_user_email'],
                    permission_data['granted_to_group_id'], permission_data['granted_to_group_name'],
                    permission_data['link_type'], permission_data['link_scope'],
                    permission_data['expires_at'], permission_data['is_active']
                ))
                
            except Exception as perm_error:
                logging.warning(f"Error processing permission {getattr(permission, 'id', 'unknown')} for {filename}: {str(perm_error)}")
                continue
        
        logging.info(f"Successfully stored {len(permissions.value)} permissions for file: {filename}")
        
    except Exception as e:
        logging.warning(f"Error extracting permissions for {filename}: {str(e)}")
        # Don't fail the entire sync if permissions fail

async def process_file_change(change, conn, cursor, graph_client=None) -> int:
    """Process a single file change and return number of chunks processed"""
    try:
        # Check if it's a file (not a folder)
        if not change.file:
            return 0
            
        filename = change.name
        file_id = change.id
        drive_id = change.parent_reference.drive_id
        
        # Check if file type is supported
        if not is_supported_file(filename):
            logging.info(f"Skipping unsupported file: {filename}")
            return 0
        
        # Check if file was deleted
        if hasattr(change, 'deleted') and change.deleted:
            logging.info(f"Deleting chunks for file: {filename}")
            try:
                # Use optimized direct file_id column for deletion
                cursor.execute("DELETE FROM chunks_v2 WHERE file_id = %s", (file_id,))
                # Also clean up file permissions
                cursor.execute("DELETE FROM file_permissions WHERE file_id = %s", (file_id,))
                conn.commit()
                logging.info(f"Successfully deleted chunks_v2 and permissions for file: {filename}")
                return 0
            except Exception as delete_error:
                logging.error(f"Error deleting chunks for {filename}: {str(delete_error)}")
                conn.rollback()
                return 0
        
        logging.info(f"Processing file: {filename}")
        
        # Extract text from file
        extracted_text = await extract_text_from_file(drive_id, file_id, filename)
        if not extracted_text or not extracted_text.strip():
            logging.warning(f"No text extracted from {filename}")
            return 0
        
        # Chunk the text
        chunks = chunk_text(extracted_text)
        logging.info(f"Created {len(chunks)} chunks for {filename}")
        
        try:
            # Delete existing chunks for this file using optimized file_id column
            cursor.execute("DELETE FROM chunks_v2 WHERE file_id = %s", (file_id,))
            
            # Process each chunk
            processed_chunks = 0
            for i, chunk in enumerate(chunks):
                # Get embedding
                embedding = await get_embedding(chunk)
                if embedding is None:
                    logging.warning(f"Failed to get embedding for chunk {i} of {filename}")
                    continue
                
                # Calculate word count for the optimized word_count column
                word_count = len(chunk.split())
                
                # Get file path for citation
                file_path = f"/{change.parent_reference.path}/{filename}" if hasattr(change, 'parent_reference') and hasattr(change.parent_reference, 'path') else f"/{filename}"
                
                # Additional metadata for flexibility (non-indexed fields)
                metadata = {
                    "total_chunks": len(chunks),
                    "last_modified": change.last_modified_date_time.isoformat() if change.last_modified_date_time else None,
                    "file_size": change.size if hasattr(change, 'size') else None,
                    "drive_name": change.parent_reference.drive_id if hasattr(change, 'parent_reference') else None
                }
                
                # Insert chunk using optimized table structure with direct columns
                cursor.execute("""
                    INSERT INTO chunks_v2 (
                        content, embedding, file_id, filename, file_path, 
                        citation_url, chunk_index, word_count, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    chunk,
                    embedding,
                    file_id,
                    filename,
                    file_path,
                    change.web_url if hasattr(change, 'web_url') else None,
                    i,
                    word_count,
                    json.dumps(metadata)
                ))
                processed_chunks += 1
            
            # Extract and store file permissions if graph_client is available
            if graph_client:
                try:
                    await extract_and_store_file_permissions(graph_client, drive_id, file_id, filename, cursor)
                    # Refresh user accessible files after permission changes
                    cursor.execute("SELECT refresh_user_accessible_files()")
                except Exception as perm_error:
                    logging.warning(f"Error processing permissions for {filename}: {str(perm_error)}")
                    # Don't fail the sync if permissions fail
            
            conn.commit()
            logging.info(f"Successfully processed {processed_chunks} chunks for {filename}")
            return processed_chunks
            
        except Exception as db_error:
            logging.error(f"Database error processing {filename}: {str(db_error)}")
            conn.rollback()
            return 0
        
    except Exception as e:
        logging.error(f"Error processing file {change.name if hasattr(change, 'name') else 'unknown'}: {str(e)}")
        return 0

async def collect_all_files(graph_client, drive_id: str, folder_id: str = 'root', current_path: str = "") -> List[Dict]:
    """Recursively collect all files in drive for batched processing"""
    all_files = []
    
    try:
        items_response = await retry_with_backoff(
            lambda: graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(folder_id).children.get()
        )
        
        if not items_response or not hasattr(items_response, 'value') or not items_response.value:
            return all_files
            
        for item in items_response.value:
            item_path = f"{current_path}/{getattr(item, 'name', 'unknown')}"
            
            if hasattr(item, 'file') and item.file:
                # Add file to collection with metadata
                all_files.append({
                    'item': item,
                    'path': item_path,
                    'type': 'file'
                })
            elif hasattr(item, 'folder') and item.folder:
                # Recursively collect from subfolder
                subfolder_files = await collect_all_files(graph_client, drive_id, item.id, item_path)
                all_files.extend(subfolder_files)
                
    except Exception as e:
        logging.error(f"Error collecting files from folder {current_path}: {str(e)}")
        # Don't fail entire collection for one folder error
        
    return all_files

async def process_file_batch(file_batch: List[Dict], conn, cursor, graph_client, progress_info: Dict) -> Dict:
    """Process a batch of files with progress tracking"""
    batch_results = {
        'processed': 0,
        'failed': 0,
        'chunks_created': 0,
        'errors': []
    }
    
    for file_info in file_batch:
        try:
            item = file_info['item']
            file_path = file_info['path']
            
            # Update progress
            progress_info['current_file'] = file_path
            await store_sync_progress(
                progress_info['drive_id'], cursor, 
                progress_info['total_files'], 
                progress_info['processed_files'], 
                progress_info['failed_files'], 
                file_path
            )
            
            # Process file with retry logic
            chunks_processed = await retry_with_backoff(
                process_file_change, item, conn, cursor, graph_client
            )
            
            batch_results['processed'] += 1
            batch_results['chunks_created'] += chunks_processed
            progress_info['processed_files'] += 1
            
            logging.info(f"Successfully processed: {file_path} ({chunks_processed} chunks)")
            
        except PermanentError as pe:
            # Don't retry permanent errors
            batch_results['failed'] += 1
            progress_info['failed_files'] += 1
            error_msg = f"Permanent error for {file_info['path']}: {str(pe)}"
            batch_results['errors'].append(error_msg)
            logging.error(error_msg)
            
        except RecoverableError as re:
            # Max retries exhausted for this file
            batch_results['failed'] += 1
            progress_info['failed_files'] += 1
            error_msg = f"Max retries exhausted for {file_info['path']}: {str(re)}"
            batch_results['errors'].append(error_msg)
            logging.error(error_msg)
            
        except Exception as e:
            # Unexpected error
            batch_results['failed'] += 1
            progress_info['failed_files'] += 1
            error_msg = f"Unexpected error for {file_info['path']}: {str(e)}"
            batch_results['errors'].append(error_msg)
            logging.error(error_msg)
    
    return batch_results

async def full_sync_drive(graph_client, drive_id: str, conn, cursor) -> int:
    """Perform robust full sync with batching, progress tracking, and error recovery"""
    logging.info(f"Starting enhanced full sync for drive: {drive_id}")
    
    # Check for existing progress
    existing_progress = await get_sync_progress(drive_id, cursor, "full")
    total_processed = 0
    
    try:
        # Step 1: Collect all files (with retry logic)
        logging.info("Phase 1: Collecting all files and folders...")
        all_files = await retry_with_backoff(collect_all_files, graph_client, drive_id)
        
        # Filter for supported file types
        supported_files = [f for f in all_files if is_supported_file(getattr(f['item'], 'name', ''))]
        
        logging.info(f"Found {len(all_files)} total items, {len(supported_files)} supported files")
        
        if not supported_files:
            logging.warning("No supported files found in drive")
            return 0
        
        # Initialize progress tracking
        progress_info = {
            'drive_id': drive_id,
            'total_files': len(supported_files),
            'processed_files': existing_progress.get('processed_files', 0),
            'failed_files': existing_progress.get('failed_files', 0),
            'current_file': ''
        }
        
        # Step 2: Process files in batches
        logging.info(f"Phase 2: Processing {len(supported_files)} files in batches of {BATCH_SIZE}")
        
        for i in range(0, len(supported_files), BATCH_SIZE):
            batch = supported_files[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(supported_files) + BATCH_SIZE - 1) // BATCH_SIZE
            
            logging.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} files)")
            
            try:
                batch_results = await process_file_batch(batch, conn, cursor, graph_client, progress_info)
                total_processed += batch_results['chunks_created']
                
                # Commit after each batch
                conn.commit()
                
                logging.info(f"Batch {batch_num} completed: {batch_results['processed']} processed, "
                           f"{batch_results['failed']} failed, {batch_results['chunks_created']} chunks created")
                
                if batch_results['errors']:
                    logging.warning(f"Batch {batch_num} errors: {'; '.join(batch_results['errors'][:3])}")
                
            except Exception as batch_error:
                logging.error(f"Critical error in batch {batch_num}: {str(batch_error)}")
                conn.rollback()
                # Continue with next batch rather than failing entire sync
                continue
        
        # Clear progress tracking on successful completion
        await clear_sync_progress(drive_id, cursor, "full")
        conn.commit()
        
        logging.info(f"Enhanced full sync completed successfully!")
        logging.info(f"Results: {progress_info['processed_files']} files processed, "
                    f"{progress_info['failed_files']} failed, {total_processed} total chunks created")
        
        return total_processed
        
    except Exception as e:
        logging.error(f"Critical error in enhanced full sync: {str(e)}")
        logging.exception("Full sync exception details:")
        
        # Store error state for potential resume
        try:
            await store_sync_progress(
                drive_id, cursor, 
                progress_info.get('total_files', 0), 
                progress_info.get('processed_files', 0), 
                progress_info.get('failed_files', 0), 
                f"ERROR: {str(e)[:100]}"
            )
            conn.commit()
        except:
            pass
            
        return total_processed

async def verify_sync_integrity(graph_client, drive_id: str, cursor) -> Dict:
    """Verify that database state matches OneDrive state"""
    logging.info(f"Starting integrity verification for drive: {drive_id}")
    
    integrity_report = {
        'onedrive_files': 0,
        'database_files': 0,
        'missing_in_db': [],
        'orphaned_in_db': [],
        'size_mismatches': [],
        'modification_mismatches': [],
        'integrity_score': 0.0
    }
    
    try:
        # Get all files from OneDrive
        onedrive_files = await collect_all_files(graph_client, drive_id)
        onedrive_file_ids = {f['item'].id: f for f in onedrive_files if hasattr(f['item'], 'file')}
        integrity_report['onedrive_files'] = len(onedrive_file_ids)
        
        # Get all files from database
        cursor.execute("SELECT DISTINCT file_id, filename, COUNT(*) as chunk_count FROM chunks_v2 GROUP BY file_id, filename")
        db_files = cursor.fetchall()
        db_file_ids = {row[0]: {'filename': row[1], 'chunk_count': row[2]} for row in db_files}
        integrity_report['database_files'] = len(db_file_ids)
        
        # Find discrepancies
        for file_id, file_info in onedrive_file_ids.items():
            if file_id not in db_file_ids:
                integrity_report['missing_in_db'].append({
                    'file_id': file_id,
                    'filename': getattr(file_info['item'], 'name', 'unknown'),
                    'path': file_info['path']
                })
        
        for file_id, db_info in db_file_ids.items():
            if file_id not in onedrive_file_ids:
                integrity_report['orphaned_in_db'].append({
                    'file_id': file_id,
                    'filename': db_info['filename'],
                    'chunk_count': db_info['chunk_count']
                })
        
        # Calculate integrity score
        total_files = max(len(onedrive_file_ids), len(db_file_ids))
        if total_files > 0:
            issues = len(integrity_report['missing_in_db']) + len(integrity_report['orphaned_in_db'])
            integrity_report['integrity_score'] = max(0.0, (total_files - issues) / total_files * 100)
        
        logging.info(f"Integrity verification completed. Score: {integrity_report['integrity_score']:.1f}%")
        logging.info(f"Issues found: {len(integrity_report['missing_in_db'])} missing, {len(integrity_report['orphaned_in_db'])} orphaned")
        
        return integrity_report
        
    except Exception as e:
        logging.error(f"Error during integrity verification: {str(e)}")
        integrity_report['error'] = str(e)
        return integrity_report

async def cleanup_orphaned_records(cursor, orphaned_files: List[Dict]) -> int:
    """Clean up orphaned database records"""
    if not orphaned_files:
        return 0
    
    cleaned = 0
    for orphan in orphaned_files:
        try:
            file_id = orphan['file_id']
            # Delete chunks
            cursor.execute("DELETE FROM chunks_v2 WHERE file_id = %s", (file_id,))
            deleted_chunks = cursor.rowcount
            
            # Delete permissions
            cursor.execute("DELETE FROM file_permissions_v2 WHERE file_id = %s", (file_id,))
            deleted_perms = cursor.rowcount
            
            logging.info(f"Cleaned up orphaned file {orphan['filename']}: {deleted_chunks} chunks, {deleted_perms} permissions")
            cleaned += 1
            
        except Exception as e:
            logging.error(f"Error cleaning up orphaned file {orphan.get('filename', 'unknown')}: {str(e)}")
    
    return cleaned

async def sync_missing_files(graph_client, drive_id: str, cursor, conn, missing_files: List[Dict]) -> int:
    """Sync files that are missing from database"""
    if not missing_files:
        return 0
    
    synced = 0
    for missing in missing_files:
        try:
            # Find the item in OneDrive and process it
            file_id = missing['file_id']
            item = await retry_with_backoff(
                lambda: graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(file_id).get()
            )
            
            if item:
                chunks_processed = await retry_with_backoff(
                    process_file_change, item, conn, cursor, graph_client
                )
                if chunks_processed > 0:
                    synced += 1
                    logging.info(f"Synced missing file: {missing['filename']} ({chunks_processed} chunks)")
                    
        except Exception as e:
            logging.error(f"Error syncing missing file {missing.get('filename', 'unknown')}: {str(e)}")
    
    return synced

async def get_delta_link_from_db(drive_id: str, cursor) -> Optional[str]:
    """Get stored delta link for a drive from database"""
    try:
        cursor.execute("SELECT delta_link FROM delta_links_v2 WHERE drive_id = %s", (drive_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        logging.error(f"Error getting delta link from database: {str(e)}")
        return None

async def store_sync_progress(drive_id: str, cursor, total_files: int = 0, processed_files: int = 0, failed_files: int = 0, current_folder: str = "", sync_type: str = "full"):
    """Store sync progress for resumability"""
    try:
        cursor.execute("""
            INSERT INTO sync_progress (drive_id, sync_type, total_files, processed_files, failed_files, current_folder, started_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (drive_id, sync_type) 
            DO UPDATE SET 
                total_files = EXCLUDED.total_files,
                processed_files = EXCLUDED.processed_files,
                failed_files = EXCLUDED.failed_files,
                current_folder = EXCLUDED.current_folder,
                updated_at = CURRENT_TIMESTAMP
        """, (drive_id, sync_type, total_files, processed_files, failed_files, current_folder))
        logging.info(f"Progress updated: {processed_files}/{total_files} files, {failed_files} failed, folder: {current_folder}")
    except Exception as e:
        logging.warning(f"Error storing sync progress: {str(e)}")

async def get_sync_progress(drive_id: str, cursor, sync_type: str = "full") -> Dict:
    """Get current sync progress"""
    try:
        cursor.execute("""
            SELECT total_files, processed_files, failed_files, current_folder, started_at
            FROM sync_progress 
            WHERE drive_id = %s AND sync_type = %s
        """, (drive_id, sync_type))
        result = cursor.fetchone()
        if result:
            return {
                'total_files': result[0],
                'processed_files': result[1], 
                'failed_files': result[2],
                'current_folder': result[3],
                'started_at': result[4]
            }
        return {}
    except Exception as e:
        logging.error(f"Error getting sync progress: {str(e)}")
        return {}

async def clear_sync_progress(drive_id: str, cursor, sync_type: str = "full"):
    """Clear sync progress after successful completion"""
    try:
        cursor.execute("DELETE FROM sync_progress WHERE drive_id = %s AND sync_type = %s", (drive_id, sync_type))
    except Exception as e:
        logging.warning(f"Error clearing sync progress: {str(e)}")

async def store_delta_link_in_db(drive_id: str, delta_link: str, cursor, files_processed: int = 0, chunks_created: int = 0, sync_status: str = 'active', error_message: str = None):
    """Store or update delta link for a drive in optimized database structure"""
    try:
        cursor.execute("""
            INSERT INTO delta_links_V2 (drive_id, delta_link, files_processed, chunks_created, sync_status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (drive_id) 
            DO UPDATE SET 
                delta_link = EXCLUDED.delta_link, 
                last_sync_at = CURRENT_TIMESTAMP,
                files_processed = EXCLUDED.files_processed,
                chunks_created = EXCLUDED.chunks_created,
                sync_status = EXCLUDED.sync_status,
                error_message = EXCLUDED.error_message,
                updated_at = CURRENT_TIMESTAMP
        """, (drive_id, delta_link, files_processed, chunks_created, sync_status, error_message))
        logging.info(f"Delta link stored for drive: {drive_id} (status: {sync_status}, files: {files_processed}, chunks: {chunks_created})")
    except Exception as e:
        logging.error(f"Error storing delta link in database: {str(e)}")

async def delta_reembed(req) -> Optional[func.HttpResponse]:
    """Main delta reembed function - supports both delta sync and full sync
    Can be triggered by timer or HTTP request"""
    
    # Determine trigger type and log accordingly
    if isinstance(req, func.TimerRequest):
        logging.info(f"Delta reembed triggered by timer. Past due: {req.past_due}")
        trigger_type = "timer"
    elif isinstance(req, func.HttpRequest):
        logging.info("Delta reembed triggered manually via HTTP")
        trigger_type = "http"
    else:
        logging.info("Delta reembed triggered manually")
        trigger_type = "manual"
    
    try:
            
        graph_client = await get_graph_client()
        
        # Connect to database
        conn = psycopg.connect(
            host=DB_HOST, 
            dbname=DB_NAME, 
            user=DB_USER, 
            password=DB_PASS, 
            sslmode="require"
        )
        cursor = conn.cursor()
        
        total_processed = 0
        current_drive_id = GRAPH_DRIVE_ID or "default"
        stored_delta_link = await get_delta_link_from_db(current_drive_id, cursor)
        logging.info(f"Stored delta link: {stored_delta_link}")
        
        # Check if full sync is enabled or no delta link exists
        if stored_delta_link is None:
            logging.info("Full sync mode enabled")
            
            if GRAPH_DRIVE_ID:
                # Sync specific drive
                total_processed = await full_sync_drive(graph_client, GRAPH_DRIVE_ID, conn, cursor)
                
                # After full sync, get current delta link and store it for future incremental syncs
                logging.info("Getting delta link after full sync completion...")
                try:
                    delta = await graph_client.drives.by_drive_id(GRAPH_DRIVE_ID).items.by_drive_item_id('01OMZHP4N6Y2GOVW7725BZO354PWSELRRZ').delta.get()
                    
                    new_delta_link = delta.odata_delta_link
                    if new_delta_link:
                        logging.info(f"Storing delta link after full sync: {new_delta_link}")
                        token = new_delta_link.split('token=')[1].split('&')[0]
                        # Count files processed during full sync (estimate based on total_processed chunks)
                        files_processed = max(1, total_processed // 5)  # Estimate ~5 chunks per file
                        await store_delta_link_in_db(current_drive_id, token, cursor, files_processed, total_processed, 'active')
                        conn.commit()
                    else:
                        logging.warning("No delta link found in response after full sync")
                        await store_delta_link_in_db(current_drive_id, "", cursor, 0, total_processed, 'error', 'No delta link found after full sync')
                        conn.commit()
                    
                except Exception as delta_error:
                    logging.error(f"Error getting delta link after full sync: {str(delta_error)}")
                    
            elif GRAPH_SITE_ID:
                # Get drive from site and sync
                site_drive = await graph_client.sites.by_site_id(GRAPH_SITE_ID).drive.get()
                if site_drive:
                    total_processed = await full_sync_drive(graph_client, site_drive.id, conn, cursor)
                    
                    # After full sync, get current delta link and store it for future incremental syncs
                    logging.info("Getting delta link after full sync completion...")
                    try:
                        delta = await graph_client.sites.by_site_id(GRAPH_SITE_ID).drive.root.delta.get()
                        if delta and hasattr(delta, 'additional_data'):
                            new_delta_link = delta.additional_data.get('@odata.deltaLink')
                            if new_delta_link:
                                logging.info(f"Storing delta link after full sync: {new_delta_link}")
                                files_processed = max(1, total_processed // 5)  # Estimate ~5 chunks per file
                                await store_delta_link_in_db(current_drive_id, new_delta_link, cursor, files_processed, total_processed, 'active')
                                conn.commit()
                            else:
                                logging.warning("No delta link found in response after full sync")
                                await store_delta_link_in_db(current_drive_id, "", cursor, 0, total_processed, 'error', 'No delta link found after site full sync')
                                conn.commit()
                        else:
                            logging.warning("Invalid delta response after full sync")
                    except Exception as delta_error:
                        logging.error(f"Error getting delta link after full sync: {str(delta_error)}")
            else:
                logging.error("Full sync enabled but no GRAPH_DRIVE_ID or GRAPH_SITE_ID configured")
                
        else:
            # Delta sync mode
            logging.info("Delta sync mode")
            
            # Build delta request
            if GRAPH_DRIVE_ID:
                if stored_delta_link:
                    logging.info(f"Using stored delta link for drive {current_drive_id}")
                    delta = await graph_client.drives.by_drive_id(GRAPH_DRIVE_ID).items.by_drive_item_id('01OMZHP4N6Y2GOVW7725BZO354PWSELRRZ').delta_with_token(stored_delta_link).get()
                    logging.info(f"Delta: {delta}")
                elif GRAPH_DELTA_LINK:
                    logging.info(f"Using environment delta link: {GRAPH_DELTA_LINK}")
                    delta = await graph_client.drives.by_drive_id(GRAPH_DRIVE_ID).root.microsoft.graph.delta.get(delta_link=GRAPH_DELTA_LINK)
                else:
                    logging.info("No existing delta link found, starting fresh delta sync")
                    delta = await graph_client.drives.by_drive_id(GRAPH_DRIVE_ID).root.microsoft.graph.delta.get()
            elif GRAPH_SITE_ID:
                if stored_delta_link:
                    logging.info(f"Using stored delta link for site drive {current_drive_id}")
                    delta = await graph_client.sites.by_site_id(GRAPH_SITE_ID).drive.root.microsoft.graph.delta.get(delta_link=stored_delta_link)
                elif GRAPH_DELTA_LINK:
                    logging.info(f"Using environment delta link: {GRAPH_DELTA_LINK}")
                    delta = await graph_client.sites.by_site_id(GRAPH_SITE_ID).drive.root.microsoft.graph.delta.get(delta_link=GRAPH_DELTA_LINK)
                else:
                    logging.info("No existing delta link found, starting fresh delta sync")
                    delta = await graph_client.sites.by_site_id(GRAPH_SITE_ID).drive.root.microsoft.graph.delta.get()
            else:
                logging.error("No GRAPH_DRIVE_ID or GRAPH_SITE_ID configured for delta sync")
                return
            
            # Get changes and new delta link
            changes = delta.value if delta else []
            new_delta_link = delta.odata_delta_link if delta else None
            new_token= urllib.parse.unquote(new_delta_link.split("token='")[1].split("'")[0])

            
            logging.info(f"Processing {len(changes)} changes")
            logging.info(f"New delta link: {new_delta_link}")
            
            # Process each change
            for change in changes:
                processed = await process_file_change(change, conn, cursor, graph_client)
                total_processed += processed
            
            # Store new delta link for next run
            if new_token:
                logging.info(f"Storing new token: {new_token}")
                files_processed = len([c for c in changes if hasattr(c, 'file') and c.file])  # Count actual files
                await store_delta_link_in_db(current_drive_id, new_token, cursor, files_processed, total_processed, 'active')
                conn.commit()
            else:
                # Store error status if no new token
                await store_delta_link_in_db(current_drive_id, stored_delta_link or "", cursor, 0, total_processed, 'error', 'No new delta token received')
                conn.commit()

        cursor.close()
        conn.close()
        
        success_message = f"Delta reembed completed successfully. Total chunks processed: {total_processed}"
        logging.info(success_message)
        
        # Return appropriate response based on trigger type
        if trigger_type == "http":
            return func.HttpResponse(
                json.dumps({
                    "status": "success", 
                    "message": success_message,
                    "chunks_processed": total_processed,
                    "trigger_type": trigger_type
                }),
                status_code=200,
                mimetype="application/json"
            )
        else:
            # For timer triggers, just return None (no HTTP response needed)
            return None
        
    except Exception as e:
        error_message = f"Error in delta_reembed: {str(e)}"
        logging.error(error_message)
        
        # Try to update sync status to error in database
        try:
            if 'cursor' in locals() and 'current_drive_id' in locals():
                await store_delta_link_in_db(
                    current_drive_id, 
                    stored_delta_link or "", 
                    cursor, 
                    0, 
                    total_processed if 'total_processed' in locals() else 0, 
                    'error', 
                    error_message[:500]  # Truncate long error messages
                )
                if 'conn' in locals():
                    conn.commit()
                    cursor.close()
                    conn.close()
        except Exception as db_error:
            logging.error(f"Error updating sync status in database: {str(db_error)}")
        
        # Return appropriate error response based on trigger type
        if trigger_type == "http":
            return func.HttpResponse(
                json.dumps({
                    "status": "error", 
                    "message": error_message,
                    "trigger_type": trigger_type
                }),
                status_code=500,
                mimetype="application/json"
            )
        else:
            # For timer triggers, re-raise the exception
            raise