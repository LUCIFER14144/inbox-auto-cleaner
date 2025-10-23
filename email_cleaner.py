
import asyncio
import json
import logging
from datetime import datetime, timedelta
import imapclient
import email
from typing import List, Dict, Any
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmailCleaner:
    def __init__(self):
        self.config = self._load_config()
        self.deletion_log = []
        self.dry_run = True  # Safety: Default to dry run mode
        
    def _load_config(self):
        """Load email configuration from environment or file"""
        config_str = os.getenv('EMAIL_CONFIG')
        if config_str:
            return json.loads(config_str)
        
        try:
            with open('config.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error("No email configuration found")
            return {"accounts": []}
    
    def enable_deletion_mode(self, confirmation_code: str):
        """Enable actual deletion (requires confirmation)"""
        if confirmation_code == "DELETE_EMAILS_PERMANENTLY_2024":
            self.dry_run = False
            logger.warning("DELETION MODE ENABLED - Emails will be permanently deleted!")
            return True
        return False
    
    async def auto_delete_old_emails(self, minutes_old: int = 60):
        """Delete emails older than specified minutes from ALL folders"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes_old)
        logger.info(f"Starting cleanup for emails older than {minutes_old} minutes (before {cutoff_time})")
        
        for account in self.config.get('accounts', []):
            try:
                await self._clean_account(account, cutoff_time)
            except Exception as e:
                logger.error(f"Error cleaning account {account['email']}: {str(e)}")
    
    async def _clean_account(self, account: Dict[str, Any], cutoff_time: datetime):
        """Clean all emails from a single account"""
        email_addr = account['email']
        password = account['password']
        
        # Determine IMAP server
        if 'yahoo' in email_addr.lower():
            imap_server = 'imap.mail.yahoo.com'
        elif 'gmail' in email_addr.lower():
            imap_server = 'imap.gmail.com'
        elif 'outlook' in email_addr.lower() or 'hotmail' in email_addr.lower():
            imap_server = 'outlook.office365.com'
        else:
            logger.warning(f"Unknown email provider for {email_addr}")
            return
        
        try:
            # Connect to IMAP server
            connection = imapclient.IMAPClient(imap_server, ssl=True)
            connection.login(email_addr, password)
            
            logger.info(f"Connected to {email_addr}")
            
            # Get all folders
            folders = connection.list_folders()
            logger.info(f"Found {len(folders)} folders in {email_addr}")
            
            total_deleted = 0
            
            for folder_info in folders:
                folder_name = folder_info[2]
                try:
                    deleted = await self._clean_folder(
                        connection, email_addr, folder_name, cutoff_time
                    )
                    total_deleted += deleted
                except Exception as e:
                    logger.error(f"Error cleaning folder {folder_name} in {email_addr}: {str(e)}")
            
            logger.info(f"Total emails processed in {email_addr}: {total_deleted}")
            connection.logout()
            
        except Exception as e:
            logger.error(f"Failed to connect to {email_addr}: {str(e)}")
    
    async def _clean_folder(self, connection, email_addr: str, folder_name: str, cutoff_time: datetime):
        """Clean emails from a specific folder"""
        try:
            connection.select_folder(folder_name)
            logger.info(f"Cleaning folder: {folder_name} in {email_addr}")
            
            # Search for all emails
            messages = connection.search(['ALL'])
            
            if not messages:
                logger.info(f"No emails found in {folder_name}")
                return 0
            
            deleted_count = 0
            
            for msg_id in messages:
                try:
                    # Fetch email headers
                    msg_data = connection.fetch(msg_id, ['RFC822.HEADER'])
                    email_message = email.message_from_bytes(
                        msg_data[msg_id][b'RFC822.HEADER']
                    )
                    
                    # Get email date
                    date_str = email_message.get('Date')
                    if date_str:
                        email_date = email.utils.parsedate_to_datetime(date_str)
                        
                        # Check if email is older than cutoff
                        if email_date.replace(tzinfo=None) < cutoff_time:
                            
                            subject = email_message.get('Subject', 'No Subject')
                            sender = email_message.get('From', 'Unknown Sender')
                            
                            # Log deletion
                            deletion_info = {
                                'account': email_addr,
                                'folder': folder_name,
                                'subject': subject,
                                'sender': sender,
                                'date': str(email_date),
                                'msg_id': str(msg_id),
                                'deleted_at': str(datetime.now()),
                                'mode': 'dry-run' if self.dry_run else 'actual-delete'
                            }
                            
                            self.deletion_log.append(deletion_info)
                            
                            if self.dry_run:
                                logger.info(f"[DRY RUN] Would delete: {subject} from {sender}")
                            else:
                                # Actually delete the email
                                connection.delete_messages([msg_id])
                                logger.warning(f"DELETED: {subject} from {sender}")
                            
                            deleted_count += 1
                
                except Exception as e:
                    logger.error(f"Error processing message {msg_id}: {str(e)}")
            
            if not self.dry_run and deleted_count > 0:
                connection.expunge()  # Permanently remove deleted messages
                
            logger.info(f"Processed {deleted_count} emails in {folder_name}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error accessing folder {folder_name}: {str(e)}")
            return 0
    
    def get_deletion_log(self):
        """Get log of all deleted emails"""
        return self.deletion_log
    
    def save_deletion_log(self, filename: str = 'deletion_log.json'):
        """Save deletion log to file"""
        with open(filename, 'w') as f:
            json.dump(self.deletion_log, f, indent=2)
        logger.info(f"Deletion log saved to {filename}")


# Background task runner
class EmailCleanerScheduler:
    def __init__(self):
        self.cleaner = EmailCleaner()
        self.running = False
    
    async def start_auto_cleanup(self, interval_minutes: int = 60, delete_after_minutes: int = 60):
        """Start automatic cleanup every interval_minutes"""
        self.running = True
        logger.info(f"Starting auto cleanup every {interval_minutes} minutes")
        
        while self.running:
            try:
                logger.info("Starting scheduled email cleanup...")
                await self.cleaner.auto_delete_old_emails(delete_after_minutes)
                self.cleaner.save_deletion_log()
                logger.info(f"Cleanup completed. Waiting {interval_minutes} minutes for next run...")
                
                # Wait for the next run
                await asyncio.sleep(interval_minutes * 60)
                
            except Exception as e:
                logger.error(f"Error in scheduled cleanup: {str(e)}")
                await asyncio.sleep(300)  # Wait 5 minutes before retry
    
    def stop_auto_cleanup(self):
        """Stop the automatic cleanup"""
        self.running = False
        logger.info("Auto cleanup stopped")
    
    def enable_deletion(self, confirmation_code: str):
        """Enable actual deletion"""
        return self.cleaner.enable_deletion_mode(confirmation_code)
