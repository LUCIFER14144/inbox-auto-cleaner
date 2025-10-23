#!/usr/bin/env python3
"""
Test script to verify email deletion functionality
Run this locally to test before deploying
"""

import asyncio
import json
import os
from datetime import datetime
from email_cleaner import EmailCleaner, EmailCleanerScheduler

async def test_dry_run():
    """Test deletion in dry-run mode"""
    print("=" * 80)
    print("STARTING DRY-RUN TEST (No emails will be deleted)")
    print("=" * 80)
    
    cleaner = EmailCleaner()
    
    # Check if config is loaded
    if not cleaner.config.get('accounts'):
        print("❌ ERROR: No email accounts configured!")
        print("Set EMAIL_CONFIG environment variable or create config.json")
        return False
    
    print(f"✓ Loaded {len(cleaner.config['accounts'])} email accounts")
    
    # Run in dry-run mode
    print("\n📧 Running email cleanup in DRY-RUN mode...")
    print("⏰ Looking for emails older than 60 minutes...")
    
    try:
        await cleaner.auto_delete_old_emails(minutes_old=60)
        
        print(f"\n✓ Dry-run completed!")
        print(f"✓ Found {len(cleaner.deletion_log)} emails that would be deleted")
        
        if cleaner.deletion_log:
            print("\n📋 Emails that would be deleted:")
            for i, entry in enumerate(cleaner.deletion_log[:5], 1):
                print(f"\n  {i}. Subject: {entry['subject']}")
                print(f"     From: {entry['sender']}")
                print(f"     Account: {entry['account']}")
                print(f"     Folder: {entry['folder']}")
                print(f"     Date: {entry['date']}")
            
            if len(cleaner.deletion_log) > 5:
                print(f"\n  ... and {len(cleaner.deletion_log) - 5} more emails")
        
        # Save log
        cleaner.save_deletion_log('test_deletion_log.json')
        print("\n✓ Deletion log saved to test_deletion_log.json")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

async def test_enable_deletion():
    """Test enabling deletion mode"""
    print("\n" + "=" * 80)
    print("TESTING DELETION MODE ENABLE")
    print("=" * 80)
    
    scheduler = EmailCleanerScheduler()
    
    # Test wrong code
    print("\n1. Testing with wrong confirmation code...")
    result = scheduler.enable_deletion("WRONG_CODE")
    if not result:
        print("   ✓ Correctly rejected wrong code")
    else:
        print("   ❌ ERROR: Should have rejected wrong code")
        return False
    
    # Test correct code
    print("\n2. Testing with correct confirmation code...")
    result = scheduler.enable_deletion("DELETE_EMAILS_PERMANENTLY_2024")
    if result:
        print("   ✓ Deletion mode enabled successfully")
        if not scheduler.cleaner.dry_run:
            print("   ✓ dry_run is now FALSE - emails WILL be deleted")
            return True
        else:
            print("   ❌ ERROR: dry_run should be False")
            return False
    else:
        print("   ❌ ERROR: Failed to enable deletion mode")
        return False

async def main():
    print("\n🧪 EMAIL CLEANER TEST SUITE\n")
    
    # Test 1: Dry run
    test1_passed = await test_dry_run()
    
    # Test 2: Enable deletion mode
    test2_passed = await test_enable_deletion()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Dry-run test: {'✓ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Deletion mode test: {'✓ PASSED' if test2_passed else '❌ FAILED'}")
    print("\n" + "=" * 80)
    
    if test1_passed and test2_passed:
        print("✓ ALL TESTS PASSED - Ready to deploy!")
        return 0
    else:
        print("❌ SOME TESTS FAILED - Fix issues before deploying")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
