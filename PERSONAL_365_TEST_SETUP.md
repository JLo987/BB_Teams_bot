# Testing OneDrive Sync with Personal Microsoft 365 Account

This guide walks you through testing your OneDrive document ingestion system using your personal Microsoft 365 account.

## 🔧 Prerequisites

- Personal Microsoft 365 account (Outlook.com, Hotmail.com, or personal tenant)
- Azure subscription (can be the same or different from your M365 account)
- Your deployed Azure Functions app with extract_text and delta_reembed functions

## 📋 Step 1: Create Azure App Registration for Personal Use

### 1.1 Create App Registration

1. Go to [Azure Portal](https://portal.azure.com) → **Azure Active Directory** → **App registrations**
2. Click **"New registration"**
3. Fill out the form:
   - **Name**: `OneDrive-Sync-Test` (or any name you prefer)
   - **Supported account types**: Select **"Personal Microsoft accounts only"** 
   - **Redirect URI**: Leave blank for now
4. Click **Register**

### 1.2 Configure API Permissions

1. In your app registration, go to **API permissions**
2. Click **"Add a permission"**
3. Select **Microsoft Graph**
4. Choose **Application permissions** (not Delegated)
5. Add these permissions:
   - `Files.Read.All` - Read all files
   - `Sites.Read.All` - Read SharePoint sites (if you have any)
   - `User.Read.All` - Read user profiles
6. Click **"Grant admin consent"** (you'll need to be admin of your own tenant)

### 1.3 Create Client Secret

1. Go to **Certificates & secrets**
2. Click **"New client secret"**
3. Add description: `OneDrive Sync Secret`
4. Choose expiration period (recommend 12 months for testing)
5. Click **Add**
6. **Copy the secret value immediately** (you won't see it again!)

### 1.4 Note Your App Details

Save these values:
- **Application (client) ID**: Found on the Overview page
- **Directory (tenant) ID**: Found on the Overview page  
- **Client Secret**: The value you just copied

## 🔍 Step 2: Discover Your Personal OneDrive

### 2.1 Set Environment Variables

```bash
# Set your app registration details
export MicrosoftAppId="your_app_id_here"
export MicrosoftAppPassword="your_client_secret_here"
export TenantId="your_tenant_id_here"
```

### 2.2 Run Discovery Script

```bash
python setup_company_onedrive.py
```

**Expected Output:**
```
🔍 Discovering SharePoint sites...
Found 1 SharePoint sites:
  1. [Your Name]'s OneDrive - https://[tenant]-my.sharepoint.com/personal/[user]/

🔍 Discovering OneDrive/SharePoint drives...
Found 1 drives:
  1. OneDrive (personal)
     Owner: [Your Name]
     Drive ID: b!xyz123...
     Web URL: https://[tenant]-my.sharepoint.com/personal/[user]/Documents

📂 Sampling content from drive: b!xyz123...
Found 10 items in root:
  📄 document1.pdf (524288 bytes) - ✅ Supported
  📄 photo.jpg (2048576 bytes) - ✅ Supported
  📁 Photos (15 items)
  📁 Desktop (8 items)
```

### 2.3 Note Your Drive ID

Save the **Drive ID** from the output (something like `b!xyz123...`)

## 📁 Step 3: Prepare Test Documents

Create a test folder in your OneDrive with various file types:

```
OneDrive/
├── TestIngestion/
    ├── sample.pdf          # PDF document
    ├── presentation.pptx   # PowerPoint
    ├── spreadsheet.xlsx    # Excel
    ├── document.docx       # Word document
    ├── notes.txt          # Text file
    ├── data.csv           # CSV file
    └── image.jpg          # Image with text (for OCR testing)
```

## ⚙️ Step 4: Configure Azure Function App

### 4.1 Update Function App Settings

In your Azure Function App, add/update these application settings:

```bash
# Microsoft Graph Authentication
MicrosoftAppId=your_app_id_here
MicrosoftAppPassword=your_client_secret_here
TenantId=your_tenant_id_here

# OneDrive Configuration
GRAPH_DRIVE_ID=your_discovered_drive_id_here
FULL_SYNC_ENABLED=true

# Function URLs (update with your actual function app name)
EXTRACT_TEXT_URL=https://your-function-app.azurewebsites.net/api/extract_text
EXTRACT_TEXT_KEY=your_extract_text_function_key
EMBED_FUNCTION_URL=https://your-function-app.azurewebsites.net/api/embed_function
EMBED_FUNCTION_KEY=your_embed_function_key

# Database Configuration (your existing settings)
DB_HOST=your_existing_db_host
DB_NAME=your_existing_db_name
DB_USER=your_existing_db_user
DB_PASS=your_existing_db_password

# Chunking Settings
CHUNK_SIZE=500
CHUNK_OVERLAP=50
```

### 4.2 Get Function Keys

1. In Azure Portal → Your Function App → Functions
2. Click on **extract_text** → Function Keys → Copy the **default** key
3. Click on **embed_function** → Function Keys → Copy the **default** key

## 🧪 Step 5: Test Individual Components

### 5.1 Test Extract Text Function

Create a test script to verify extract_text works:

```python
# test_extract_text.py
import requests
import json

# Your function details
EXTRACT_TEXT_URL = "https://your-app.azurewebsites.net/api/extract_text"
EXTRACT_TEXT_KEY = "your_function_key"

# Test with a file from your OneDrive
test_data = {
    "drive_id": "your_drive_id",
    "file_id": "file_id_of_test_document",  # Get this from Graph Explorer
    "filename": "sample.pdf"
}

headers = {"x-functions-key": EXTRACT_TEXT_KEY}

response = requests.post(EXTRACT_TEXT_URL, json=test_data, headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

### 5.2 Get File ID for Testing

Use [Microsoft Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer):

1. Sign in with your personal account
2. Run: `GET https://graph.microsoft.com/v1.0/me/drive/root/children`
3. Find a test file and copy its `id` field

### 5.3 Test the Extract Function

```bash
python test_extract_text.py
```

Expected output:
```json
{
    "text": "Extracted text content from your PDF...",
    "source": "sample.pdf",
    "drive_id": "b!xyz123...",
    "file_id": "01ABC123..."
}
```

## 🔄 Step 6: Test Full Sync

### 6.1 Create Delta Links Table

```bash
python manage_delta_links.py create-table
```

### 6.2 Trigger Full Sync

Option A - **Manual Trigger** (recommended for testing):
```bash
# Using Azure CLI
az functionapp function invoke \
  --resource-group your-resource-group \
  --name your-function-app-name \
  --function-name delta_reembed
```

Option B - **Wait for Scheduled Run** (2 AM daily)

### 6.3 Monitor Progress

**Check Function Logs:**
1. Azure Portal → Your Function App → Functions → delta_reembed
2. Go to **Monitor** → **Logs**
3. Look for logs like:
```
Full sync mode enabled
Starting full sync for drive: b!xyz123...
Processing file: sample.pdf
Created 3 chunks for sample.pdf
Successfully processed 3 chunks for sample.pdf
Full sync completed. Processed 25 chunks total.
```

**Check Database:**
```sql
-- Total chunks created
SELECT COUNT(*) as total_chunks FROM chunks;

-- Files processed  
SELECT COUNT(DISTINCT source_id) as unique_files FROM chunks;

-- Recent activity
SELECT 
    metadata->>'filename' as filename,
    COUNT(*) as chunks,
    MAX(created_at) as processed_at
FROM chunks 
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY metadata->>'filename'
ORDER BY processed_at DESC;
```

## 🧹 Step 7: Test Delta Sync

### 7.1 Make Changes to Your OneDrive

1. Add a new document to your test folder
2. Modify an existing document
3. Delete a document

### 7.2 Switch to Delta Mode

Update Function App settings:
```bash
FULL_SYNC_ENABLED=false
```

### 7.3 Trigger Delta Sync

```bash
# Manual trigger
az functionapp function invoke \
  --resource-group your-resource-group \
  --name your-function-app-name \
  --function-name delta_reembed
```

### 7.4 Verify Delta Changes

Check logs for delta sync activity:
```
Delta sync mode
Using stored delta link for drive b!xyz123...
Processing 3 changes
Processing file: new_document.pdf
Deleting chunks for file: deleted_document.pdf
Delta reembed completed successfully. Total chunks processed: 5
```

## 🛠️ Step 8: Troubleshooting

### Common Issues and Solutions

**1. Authentication Errors**
```
Error: Failed to get access token
```
- Verify app registration permissions
- Check client ID, secret, and tenant ID
- Ensure admin consent was granted

**2. File Access Errors**
```
Error downloading from OneDrive: Forbidden
```
- Check that Files.Read.All permission is granted
- Verify you're using the correct drive ID

**3. Function Timeout**
```
Error: Request timed out (120s)
```
- Test with smaller files first
- Check if OCR dependencies are properly installed

**4. Database Connection Issues**
```
Error: Connection to database failed
```
- Verify database connection string
- Check firewall rules allow Azure Functions

### Debugging Commands

```bash
# Check delta links
python manage_delta_links.py list

# Reset delta state (forces full resync)
python manage_delta_links.py delete "your_drive_id"

# Database health check
python manage_delta_links.py validate
```

## ✅ Success Verification

Your test is successful when you see:

1. **Extract Text Working**: Individual files return extracted text
2. **Full Sync Complete**: All test documents appear in database
3. **Delta Sync Working**: Changes to OneDrive reflect in database
4. **Proper Chunking**: Documents split into appropriate chunks
5. **Metadata Preserved**: File information stored correctly

## 🎯 Next Steps

Once testing is successful:

1. **Reset for Production**: 
   ```bash
   python manage_delta_links.py reset-all
   ```

2. **Configure for Company OneDrive**:
   - Update app registration for company tenant
   - Use company drive ID
   - Set appropriate permissions

3. **Deploy with Confidence**: Your system is tested and ready!

## 📞 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review function logs in Azure Portal
3. Verify all environment variables are set correctly
4. Test with simpler file types first (txt, csv) before complex ones (pdf, images)

Happy testing! 🚀