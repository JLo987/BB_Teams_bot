#!/usr/bin/env python3
"""
Utility script to set up a new company OneDrive for automated document sync.
This script helps discover drive IDs and configure the delta_reembed function.
"""

import os
import sys
import requests
import json
import asyncio
from typing import List, Dict, Optional
from msal import ConfidentialClientApplication

# Configuration - set these as environment variables or update here
APP_ID = os.getenv("MicrosoftAppId", "")
APP_SECRET = os.getenv("MicrosoftAppPassword", "")
TENANT_ID = os.getenv("TenantId", "")

class GraphHelper:
    def __init__(self):
        self.app = ConfidentialClientApplication(
            APP_ID,
            authority=f"https://login.microsoftonline.com/{TENANT_ID}",
            client_credential=APP_SECRET
        )
        self.access_token = None
    
    def get_access_token(self):
        """Get access token for Microsoft Graph"""
        if self.access_token:
            return self.access_token
            
        result = self.app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        
        if "access_token" in result:
            self.access_token = result["access_token"]
            return self.access_token
        else:
            raise Exception(f"Failed to get access token: {result}")
    
    def make_graph_request(self, endpoint: str, method: str = "GET") -> Dict:
        """Make a request to Microsoft Graph API"""
        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        url = f"https://graph.microsoft.com/v1.0{endpoint}"
        response = requests.request(method, url, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Graph API request failed: {response.status_code} - {response.text}")

def discover_sharepoint_sites(graph_helper: GraphHelper) -> List[Dict]:
    """Discover all SharePoint sites in the tenant"""
    print("🔍 Discovering SharePoint sites...")
    
    sites = []
    
    try:
        # Try multiple approaches to get sites
        approaches = [
            ("/sites", "Basic sites endpoint"),
            ("/sites?search=''", "Empty search"),
            ("/sites/getAllSites", "GetAllSites endpoint"),
            ("/sites/root", "Root site collection")
        ]
        
        for endpoint, description in approaches:
            try:
                print(f"   Trying {description}...")
                result = graph_helper.make_graph_request(endpoint)
                
                if endpoint == "/sites/root":
                    # Single site response
                    if result.get('id'):
                        sites.append(result)
                        break
                else:
                    # Collection response
                    found_sites = result.get("value", [])
                    if found_sites:
                        sites.extend(found_sites)
                        break
                        
            except Exception as approach_error:
                print(f"   ❌ {description} failed: {str(approach_error)}")
                continue
        
        if sites:
            print(f"Found {len(sites)} SharePoint sites:")
            for i, site in enumerate(sites):
                print(f"  {i+1}. {site.get('displayName', 'Unknown')} - {site.get('webUrl', '')}")
                print(f"     Site ID: {site.get('id', '')}")
        else:
            print("❌ No sites found with any approach. This might be a permissions issue.")
        
        return sites
        
    except Exception as e:
        print(f"❌ Error discovering sites: {str(e)}")
        return []

def discover_drives(graph_helper: GraphHelper, site_id: str = None) -> List[Dict]:
    """Discover drives in a site or for the organization"""
    print("🔍 Discovering OneDrive/SharePoint drives...")
    
    drives = []
    
    try:
        if site_id:
            # Get drives for specific site
            try:
                print(f"   Searching drives for site: {site_id}")
                result = graph_helper.make_graph_request(f"/sites/{site_id}/drives")
                site_drives = result.get("value", [])
                drives.extend(site_drives)
            except Exception as e:
                print(f"   ❌ Site-specific drive discovery failed: {str(e)}")
        else:
            # Try multiple approaches for organization drives
            approaches = [
                ("/drives", "All organizational drives"),
                ("/me/drives", "Current user drives"),
                ("/sites/root/drives", "Root site drives")
            ]
            
            for endpoint, description in approaches:
                try:
                    print(f"   Trying {description}...")
                    result = graph_helper.make_graph_request(endpoint)
                    found_drives = result.get("value", [])
                    if found_drives:
                        drives.extend(found_drives)
                        print(f"   ✅ Found {len(found_drives)} drives with {description}")
                        break
                except Exception as approach_error:
                    print(f"   ❌ {description} failed: {str(approach_error)}")
                    continue
        
        if drives:
            print(f"Found {len(drives)} drives:")
            for i, drive in enumerate(drives):
                drive_type = drive.get("driveType", "unknown")
                owner = drive.get("owner", {}).get("user", {}).get("displayName", "Unknown")
                print(f"  {i+1}. {drive.get('name', 'Unknown')} ({drive_type})")
                print(f"     Owner: {owner}")
                print(f"     Drive ID: {drive.get('id', '')}")
                print(f"     Web URL: {drive.get('webUrl', '')}")
                print()
        else:
            print("❌ No drives found with any approach. This might be a permissions issue.")
        
        return drives
        
    except Exception as e:
        print(f"❌ Error discovering drives: {str(e)}")
        return []

def sample_drive_content(graph_helper: GraphHelper, drive_id: str, max_items: int = 10) -> List[Dict]:
    """Sample content from a drive to understand its structure"""
    print(f"📂 Sampling content from drive: {drive_id}")
    
    try:
        # Get root items
        result = graph_helper.make_graph_request(f"/drives/{drive_id}/root/children?$top={max_items}")
        items = result.get("value", [])
        
        print(f"Found {len(items)} items in root:")
        supported_types = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', 
                          '.txt', '.csv', '.jpg', '.jpeg', '.png', '.tif', '.tiff']
        
        document_count = 0
        for item in items:
            if item.get("file"):
                name = item.get("name", "Unknown")
                id = item.get("id", "Unknown")
                size = item.get("size", 0)
                extension = '.' + name.lower().split('.')[-1] if '.' in name else ''
                is_supported = extension in supported_types
                
                if is_supported:
                    document_count += 1
                    status = "✅ Supported"
                else:
                    status = "❌ Not supported"
                
                print(f"  📄 {name} ({size} bytes) {id}- {status}")
            elif item.get("folder"):
                child_count = item.get("folder", {}).get("childCount", 0)
                print(f"  📁 {item.get('name', 'Unknown')} ({child_count} items)")
        
        print(f"\n📊 Summary: {document_count} supported documents found in sample")
        return items
        
    except Exception as e:
        print(f"❌ Error sampling drive content: {str(e)}")
        return []

def estimate_full_sync_size(graph_helper: GraphHelper, drive_id: str) -> Dict:
    """Estimate the size and scope of a full sync"""
    print(f"📏 Estimating full sync size for drive: {drive_id}")
    
    try:
        # Get drive info
        drive_info = graph_helper.make_graph_request(f"/drives/{drive_id}")
        quota = drive_info.get("quota", {})
        
        total_size = quota.get("total", 0)
        used_size = quota.get("used", 0)
        
        print(f"Drive storage: {used_size / (1024**3):.2f} GB used of {total_size / (1024**3):.2f} GB total")
        
        # Get file count estimate by getting root children (recursive sample)
        search_result = graph_helper.make_graph_request(f"/drives/{drive_id}/root/children?$top=1000")
        sample_files = search_result.get("value", [])
        
        supported_types = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', 
                          '.txt', '.csv', '.jpg', '.jpeg', '.png', '.tif', '.tiff']
        
        supported_count = 0
        total_doc_size = 0
        
        for file in sample_files:
            if file.get("file"):
                name = file.get("name", "")
                id = file.get("id", "")
                extension = '.' + name.lower().split('.')[-1] if '.' in name else ''
                if extension in supported_types:
                    supported_count += 1
                    total_doc_size += file.get("size", 0)
        
        estimate = {
            "total_files_sampled": len(sample_files),
            "supported_files_sampled": supported_count,
            "avg_doc_size": total_doc_size / max(supported_count, 1),
            "estimated_processing_time_hours": (supported_count * 2) / 3600,  # ~2 seconds per doc
            "drive_used_gb": used_size / (1024**3),
            "drive_total_gb": total_size / (1024**3)
        }
        
        print(f"Estimation based on {len(sample_files)} sampled files:")
        print(f"  - Supported document types: {supported_count}")
        print(f"  - Average document size: {estimate['avg_doc_size'] / 1024:.1f} KB")
        print(f"  - Estimated processing time: {estimate['estimated_processing_time_hours']:.1f} hours")
        
        return estimate
        
    except Exception as e:
        print(f"❌ Error estimating sync size: {str(e)}")
        return {}

def generate_config_template(drive_id: str, site_id: str = None) -> str:
    """Generate environment variable configuration template"""
    config = f"""
# OneDrive/SharePoint Configuration for delta_reembed
# Add these to your Azure Function App Settings

# Required: Drive to sync
GRAPH_DRIVE_ID={drive_id}

# Optional: Site ID (if using site-based sync)
{f'GRAPH_SITE_ID={site_id}' if site_id else '# GRAPH_SITE_ID=your_site_id_here'}

# Full sync mode (set to 'true' for initial sync, then 'false' for delta)
FULL_SYNC_ENABLED=true

# Optional: Chunking configuration
CHUNK_SIZE=500
CHUNK_OVERLAP=50

# Required: Function URLs (update with your function app URL)
EMBED_FUNCTION_URL=https://your-function-app.azurewebsites.net/api/embed_function
EMBED_FUNCTION_KEY=your_embed_function_key
EXTRACT_TEXT_URL=https://your-function-app.azurewebsites.net/api/extract_text
EXTRACT_TEXT_KEY=your_extract_text_function_key

# Database configuration
DB_HOST=your_db_host
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASS=your_db_password

# Microsoft Graph authentication (should already be configured)
MicrosoftAppId=your_app_id
MicrosoftAppPassword=your_app_secret
TenantId=your_tenant_id
"""
    return config

def test_authentication(graph_helper: GraphHelper) -> bool:
    """Test basic authentication and permissions"""
    print("🔐 Testing authentication...")
    
    try:
        # Test basic Graph access with /me endpoint (if available)
        try:
            result = graph_helper.make_graph_request("/me")
            print("✅ App has delegated permissions (personal context)")
            return True
        except Exception:
            pass
        
        # Test application permissions with organization endpoint
        try:
            result = graph_helper.make_graph_request("/organization")
            print("✅ App has application permissions (organization context)")
            return True
        except Exception:
            pass
        
        # Test minimal Graph access
        try:
            result = graph_helper.make_graph_request("/")
            print("✅ Basic Graph API access confirmed")
            return True
        except Exception as e:
            print(f"❌ Authentication failed: {str(e)}")
            return False
            
    except Exception as e:
        print(f"❌ Authentication test failed: {str(e)}")
        return False

def main():
    """Main setup workflow"""
    print("🚀 Company OneDrive Setup Utility")
    print("=" * 50)
    
    # Validate configuration
    if not all([APP_ID, APP_SECRET, TENANT_ID]):
        print("❌ Missing required environment variables:")
        print("   - MicrosoftAppId")
        print("   - MicrosoftAppPassword") 
        print("   - TenantId")
        print("\nPlease set these environment variables and try again.")
        return
    
    try:
        graph_helper = GraphHelper()
        
        # Test authentication first
        if not test_authentication(graph_helper):
            print("\n❌ Authentication failed. Please check:")
            print("1. App registration exists in Azure Portal")
            print("2. Client secret is valid and not expired")
            print("3. App has been granted admin consent")
            print("4. Required API permissions are configured")
            return
        
        # Step 1: Discover SharePoint sites
        sites = discover_sharepoint_sites(graph_helper)
        if not sites:
            print("❌ No SharePoint sites found or accessible.")
            print("\n💡 Trying alternative approach: Direct drive discovery...")
            # Skip to drive discovery without site context
            sites = []
        
        # Step 2: Let user select a site
        print("\n" + "=" * 50)
        site_choice = input("Enter the number of the site to configure (or 'skip' to discover all drives): ").strip()
        
        selected_site = None
        if site_choice.lower() != 'skip' and site_choice.isdigit():
            site_index = int(site_choice) - 1
            if 0 <= site_index < len(sites):
                selected_site = sites[site_index]
                print(f"✅ Selected site: {selected_site.get('displayName')}")
        
        # Step 3: Discover drives
        print("\n" + "=" * 50)
        if selected_site:
            drives = discover_drives(graph_helper, selected_site.get('id'))
        else:
            drives = discover_drives(graph_helper)
        
        if not drives:
            print("❌ No drives found or accessible.")
            return
        
        # Step 4: Let user select a drive
        print("\n" + "=" * 50)
        drive_choice = input("Enter the number of the drive to configure: ").strip()
        
        if not drive_choice.isdigit():
            print("❌ Invalid selection.")
            return
        
        drive_index = int(drive_choice) - 1
        if not (0 <= drive_index < len(drives)):
            print("❌ Invalid drive selection.")
            return
        
        selected_drive = drives[drive_index]
        drive_id = selected_drive.get('id')
        
        print(f"✅ Selected drive: {selected_drive.get('name')}")
        print(f"Drive ID: {drive_id}")
        
        # Step 5: Sample drive content
        print("\n" + "=" * 50)
        sample_drive_content(graph_helper, drive_id)
        
        # Step 6: Estimate sync size
        print("\n" + "=" * 50)
        estimate_full_sync_size(graph_helper, drive_id)
        
        # Step 7: Generate configuration
        print("\n" + "=" * 50)
        print("📋 Configuration Template")
        print("=" * 50)
        
        site_id = selected_site.get('id') if selected_site else None
        config_template = generate_config_template(drive_id, site_id)
        print(config_template)
        
        # Save to file
        config_filename = f"onedrive_config_{selected_drive.get('name', 'drive').replace(' ', '_')}.txt"
        with open(config_filename, 'w') as f:
            f.write(config_template)
        print(f"💾 Configuration saved to: {config_filename}")
        
        # Step 8: Next steps
        print("\n" + "=" * 50)
        print("🎯 Next Steps:")
        print("=" * 50)
        print("1. Update your Azure Function App settings with the configuration above")
        print("2. Set FULL_SYNC_ENABLED=true for the initial sync")
        print("3. Manually trigger the delta_reembed function or wait for the timer")
        print("4. After initial sync completes, set FULL_SYNC_ENABLED=false")
        print("5. The function will now run nightly for delta sync")
        print(f"6. Monitor logs for sync progress and errors")
        
    except Exception as e:
        print(f"❌ Setup failed: {str(e)}")

if __name__ == "__main__":
    main()