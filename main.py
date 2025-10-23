
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import imaplib
import email
from email.header import decode_header
import ssl
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from email_cleaner import EmailCleanerScheduler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic models
class SearchRequest(BaseModel):
    sender_email: Optional[str] = None
    subject: Optional[str] = None

    @classmethod
    def validate(cls, value):
        if not value.get('sender_email') and not value.get('subject'):
            raise ValueError("At least one of sender_email or subject must be provided")
        return value

class EmailResult(BaseModel):
    provider: str
    folder: str
    time_received: str
    account_email: str

class SearchResponse(BaseModel):
    results: List[EmailResult]
    total_checked: int
    search_id: str

# Global variables for background tasks
search_results_cache = {}
active_searches = {}
cleaner_scheduler = EmailCleanerScheduler()

# Load configuration
def load_config():
    """Load email accounts from environment variable or config.json"""
    try:
        # First try to load from environment variable
        config_str = os.getenv('EMAIL_CONFIG')
        if config_str:
            return json.loads(config_str)
        
        # Fallback to config.json
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("config.json not found")
        return {"accounts": []}
    except json.JSONDecodeError:
        logger.error("Invalid JSON in config or config.json")
        return {"accounts": []}
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        return {"accounts": []}

def get_folder_type(folder_name: str, provider: str) -> str:
    """Determine folder type based on folder name and provider"""
    folder_lower = folder_name.lower()

    # Gmail folder mappings
    if provider.lower() == 'gmail':
        if folder_lower in ['inbox', '[gmail]/all mail']:
            return 'inbox'
        elif folder_lower in ['[gmail]/spam', '[gmail]/junk']:
            return 'spam'
        elif folder_lower in ['[gmail]/promotions']:
            return 'promotions'

    # Yahoo folder mappings
    elif provider.lower() == 'yahoo':
        if folder_lower in ['inbox']:
            return 'inbox'
        elif folder_lower in ['bulk mail', 'spam', 'junk']:
            return 'spam'
        elif folder_lower in ['promotions']:
            return 'promotions'

    # Outlook/Hotmail folder mappings
    elif provider.lower() in ['outlook', 'hotmail']:
        if folder_lower in ['inbox']:
            return 'inbox'
        elif folder_lower in ['junk email', 'spam']:
            return 'spam'
        elif folder_lower in ['promotions']:
            return 'promotions'

    # Default mappings for other providers
    if any(word in folder_lower for word in ['inbox']):
        return 'inbox'
    elif any(word in folder_lower for word in ['spam', 'junk', 'bulk']):
        return 'spam'
    elif any(word in folder_lower for word in ['promotion', 'marketing', 'offers']):
        return 'promotions'

    return 'inbox'

def get_provider_from_email(email_address: str) -> str:
    """Extract provider from email address"""
    domain = email_address.split('@')[-1].lower()
    if 'gmail' in domain:
        return 'gmail'
    elif 'yahoo' in domain:
        return 'yahoo'
    elif 'outlook' in domain or 'hotmail' in domain or 'live' in domain:
        return 'outlook'
    else:
        return domain

def get_imap_server(email_address: str) -> str:
    """Get IMAP server based on email provider"""
    domain = email_address.split('@')[-1].lower()

    if 'gmail' in domain:
        return 'imap.gmail.com'
    elif 'yahoo' in domain:
        return 'imap.mail.yahoo.com'
    elif 'outlook' in domain or 'hotmail' in domain or 'live' in domain:
        return 'outlook.office365.com'
    else:
        return f'imap.{domain}'

async def search_single_account(account: Dict, sender_email: str, subject: str, search_id: str) -> List[EmailResult]:
    """Search a single email account for matching emails"""
    results = []

    try:
        imap_server = get_imap_server(account['email'])
        provider = get_provider_from_email(account['email'])

        # Connect to IMAP server
        try:
            mail = imaplib.IMAP4_SSL(imap_server, 993)
            mail.login(account['email'], account['password'])
            logger.info(f"Successfully connected to {imap_server} for {account['email']}")
        except Exception as e:
            logger.error(f"Failed to connect to {imap_server} for {account['email']}: {str(e)}")
            return results

        # List all folders
        try:
            status, folders = mail.list()
            if status != 'OK':
                logger.error(f"Failed to list folders for {account['email']}")
                return results
            logger.info(f"Successfully listed folders for {account['email']}")
        except Exception as e:
            logger.error(f"Error listing folders for {account['email']}: {str(e)}")
            return results

        # Search in common folders
        search_folders = ['INBOX']

        # Add provider-specific folders
        if provider == 'gmail':
            search_folders.extend(['[Gmail]/Spam', '[Gmail]/Promotions', '[Gmail]/All Mail'])
        elif provider == 'yahoo':
            status, folder_list = mail.list()
            if status == 'OK':
                for folder_data in folder_list:
                    folder_info = folder_data.decode().split(' "/" ')
                    if len(folder_info) > 1:
                        folder = folder_info[-1].strip('"')
                        if any(name in folder.lower() for name in ['bulk', 'spam', 'junk']):
                            search_folders.append(folder)
            logger.info(f"Yahoo folders found: {search_folders}")
        elif provider == 'outlook':
            search_folders.extend(['Junk Email'])

        for folder_name in search_folders:
            try:
                # Select folder
                try:
                    status, messages = mail.select(f'"{folder_name}"' if provider == 'yahoo' else folder_name, readonly=True)
                    if status != 'OK':
                        logger.error(f"Failed to select folder {folder_name} for {account['email']}")
                        continue
                    logger.info(f"Selected folder {folder_name} for {account['email']}")
                except Exception as e:
                    logger.error(f"Error selecting folder {folder_name} for {account['email']}: {str(e)}")
                    continue

                # Build search criteria
                search_criteria = []
                if sender_email:
                    search_criteria.append(f'FROM "{sender_email}"')
                if subject:
                    search_criteria.append(f'SUBJECT "{subject}"')

                if not search_criteria:
                    continue

                # Search for emails
                search_query = f'({" ".join(search_criteria)})'
                logger.info(f"Searching with query: {search_query} in {folder_name} for {account['email']}")
                try:
                    status, message_ids = mail.search(None, search_query)
                    if status != 'OK':
                        logger.error(f"Search failed in {folder_name} for {account['email']}")
                        continue
                    logger.info(f"Search successful in {folder_name} for {account['email']}")
                except Exception as e:
                    logger.error(f"Error searching in {folder_name} for {account['email']}: {str(e)}")
                    continue

                if status == 'OK' and message_ids[0]:
                    ids = message_ids[0].split()

                    for msg_id in ids[-10:]:
                        try:
                            # Fetch email data
                            status, msg_data = mail.fetch(msg_id, '(RFC822)')
                            if status != 'OK':
                                continue

                            # Parse email
                            email_message = email.message_from_bytes(msg_data[0][1])

                            # Get received date
                            date_header = email_message.get('Date', '')
                            try:
                                received_time = email.utils.parsedate_to_datetime(date_header)
                                time_str = received_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                            except:
                                time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

                            # Determine folder type
                            folder_type = get_folder_type(folder_name, provider)

                            result = EmailResult(
                                provider=provider.title(),
                                folder=folder_type,
                                time_received=time_str,
                                account_email=account['email']
                            )
                            results.append(result)
                            
                        except Exception as e:
                            logger.error(f"Error processing email: {str(e)}")
                            continue

            except Exception as e:
                logger.error(f"Error processing folder {folder_name}: {str(e)}")
                continue

        mail.close()
        mail.logout()

    except Exception as e:
        logger.error(f"Error searching account {account['email']}: {str(e)}")

    return results

async def background_search(search_request: SearchRequest, search_id: str):
    """Background task to search all accounts"""
    config = load_config()
    accounts = config.get('accounts', [])

    if not accounts:
        logger.error("No accounts configured")
        search_results_cache[search_id] = {
            'results': [],
            'total_checked': 0
        }
        return

    active_searches[search_id] = {
        'status': 'searching',
        'completed': 0,
        'total': len(accounts),
        'results': []
    }

    all_results = []

    for i, account in enumerate(accounts):
        try:
            results = await search_single_account(
                account,
                search_request.sender_email,
                search_request.subject,
                search_id
            )
            all_results.extend(results)
        except Exception as e:
            logger.error(f"Error searching account {account.get('email', 'unknown')}: {str(e)}")

        active_searches[search_id]['completed'] = i + 1
        active_searches[search_id]['results'] = all_results

    # Cache final results
    search_results_cache[search_id] = {
        'results': all_results,
        'total_checked': len(accounts)
    }

    # Update active search status
    active_searches[search_id]['status'] = 'completed'

    logger.info(f"Search {search_id} completed with {len(all_results)} results")

# FastAPI app
app = FastAPI(title="Inbox Auto-Cleaner", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_root():
    """Serve the frontend HTML"""
    return FileResponse('static/index.html')

@app.get("/admin")
async def admin_page():
    """Serve admin page"""
    return FileResponse('static/admin.html')

@app.post("/api/search")
async def start_search(search_request: SearchRequest, background_tasks: BackgroundTasks):
    """Start email search across all configured accounts"""
    # Validate that at least one search criteria is provided
    if not search_request.sender_email and not search_request.subject:
        raise HTTPException(
            status_code=400,
            detail="At least one search criteria (sender_email or subject) must be provided"
        )

    search_id = f"search_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    # Start background search
    background_tasks.add_task(background_search, search_request, search_id)

    return {"search_id": search_id, "message": "Search started"}

@app.get("/api/search/{search_id}/status")
async def get_search_status(search_id: str):
    """Get search status and partial results"""
    if search_id in active_searches:
        search_info = active_searches[search_id]
        return {
            "status": search_info['status'],
            "completed": search_info['completed'],
            "total": search_info['total'],  
            "results": search_info['results']
        }
    elif search_id in search_results_cache:
        cached_result = search_results_cache[search_id]
        return {
            "status": "completed",
            "completed": cached_result['total_checked'],
            "total": cached_result['total_checked'],
            "results": cached_result['results']
        }
    else:
        raise HTTPException(status_code=404, detail="Search not found")

@app.get("/api/search/{search_id}/results")
async def get_search_results(search_id: str):
    """Get final search results"""
    if search_id in search_results_cache:
        cached_result = search_results_cache[search_id]
        return SearchResponse(
            results=cached_result['results'],
            total_checked=cached_result['total_checked'],
            search_id=search_id
        )
    else:
        raise HTTPException(status_code=404, detail="Search results not found")

@app.get("/api/accounts")
async def get_accounts():
    """Get list of configured accounts"""
    config = load_config()
    accounts = []
    for account in config.get('accounts', []):
        accounts.append({
            'email': account.get('email', ''),
            'name': account.get('name', account.get('email', ''))
        })
    return {'accounts': accounts}

# Auto-delete endpoints
@app.post("/admin/enable-deletion")
async def enable_deletion(request: Request):
    """Enable email deletion (DANGEROUS!)"""
    data = await request.json()
    confirmation_code = data.get('confirmation_code', '')
    
    if cleaner_scheduler.enable_deletion(confirmation_code):
        return {"status": "success", "message": "Deletion mode enabled - BE VERY CAREFUL!"}
    else:
        return {"status": "error", "message": "Invalid confirmation code"}

@app.post("/admin/start-auto-delete")
async def start_auto_delete(request: Request, background_tasks: BackgroundTasks):
    """Start automatic deletion process"""
    data = await request.json()
    interval_minutes = data.get('interval_minutes', 60)
    delete_after_minutes = data.get('delete_after_minutes', 60)
    
    # Start the cleanup in background
    background_tasks.add_task(
        cleaner_scheduler.start_auto_cleanup, interval_minutes, delete_after_minutes
    )
    
    return {
        "status": "success", 
        "message": f"Auto-deletion started: checking every {interval_minutes} minutes, deleting emails older than {delete_after_minutes} minutes"
    }

@app.post("/admin/stop-auto-delete")
async def stop_auto_delete():
    """Stop automatic deletion process"""
    cleaner_scheduler.stop_auto_cleanup()
    return {"status": "success", "message": "Auto-deletion stopped"}

@app.get("/admin/deletion-log")
async def get_deletion_log():
    """Get deletion log"""
    return {"log": cleaner_scheduler.cleaner.get_deletion_log()}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
