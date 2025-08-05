# OneDrive Document Extraction Setup Guide

This guide explains how to set up and use the OneDrive document extraction functionality for your RAG bot.

## Overview

The system now supports extracting text from documents stored in OneDrive/SharePoint using the new `extract_text` Azure Function. This function can process various file types including:

- **Images**: JPG, JPEG, PNG, TIF, TIFF (with OCR)
- **PDFs**: Text extraction + OCR fallback
- **Office Documents**: Word (.docx), Excel (.xlsx, .xls), PowerPoint (.pptx)
- **Text Files**: TXT, CSV

## Architecture Decision: Azure Functions vs Containers

**✅ Recommended: Azure Functions**

We chose Azure Functions for the extract_text functionality because:

- **Consistency**: Aligns with your existing architecture
- **Serverless scaling**: Automatically handles varying loads
- **Cost efficiency**: Pay only for execution time
- **Built-in integrations**: Works seamlessly with Microsoft Graph
- **Simplified deployment**: Uses your existing CI/CD pipeline

**Alternative: Container Deployment**

While containers would provide more control and potentially better performance for heavy OCR workloads, Azure Functions can handle the OCR dependencies (pytesseract, pdf2image) effectively with proper configuration.

## Setup Instructions

### 1. Environment Variables

Add these environment variables to your Azure Functions app:

```bash
# Existing variables (already configured)
EMBED_FUNCTION_URL=https://your-function-app.azurewebsites.net/api/embed_function
EMBED_FUNCTION_KEY=your_function_key

# New variables for OneDrive extraction
EXTRACT_TEXT_URL=https://your-function-app.azurewebsites.net/api/extract_text
EXTRACT_TEXT_KEY=your_function_key

# Microsoft Graph (already configured for your bot)
MicrosoftAppId=your_app_id
MicrosoftAppPassword=your_app_secret
TenantId=your_tenant_id
```

### 2. Deploy the Updated Function App

The updated function app includes:
- New `extract_text` function in `/LocalFunctionProj/extract_text/`
- Updated `requirements.txt` with OCR dependencies
- Updated `function_app.py` to register the new route

Deploy using your existing method:

```bash
# If using Azure CLI
func azure functionapp publish your-function-app-name --python

# Or use your CI/CD pipeline
```

### 3. Install OCR Dependencies (Azure Functions)

The `requirements.txt` now includes OCR dependencies. For Azure Functions to use Tesseract OCR, you may need to:

1. **Option A**: Use the Linux consumption plan (recommended)
2. **Option B**: Include Tesseract binaries in your deployment
3. **Option C**: Use Azure Container Instances if OCR performance is critical

### 4. Configure Database Schema

Ensure your `chunks` table supports the `source_id` column for OneDrive files:

```sql
-- Add source_id column if it doesn't exist
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS source_id VARCHAR(255) UNIQUE;

-- Create index for better performance
CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id);
```

## Usage

### 1. Identify OneDrive Files

First, you need to get the `drive_id` and `file_id` for files you want to process. You can use Microsoft Graph Explorer or the Graph API:

```bash
# Get drives
GET https://graph.microsoft.com/v1.0/me/drives

# Get files in a drive
GET https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children

# Search for files
GET https://graph.microsoft.com/v1.0/drives/{drive_id}/root/search(q='finance')
```

### 2. Create a File List JSON

Create a JSON file with the files you want to ingest:

```json
[
  {
    "drive_id": "b!xyz123...",
    "file_id": "01ABC123...",
    "filename": "quarterly_report.pdf",
    "citation_url": "https://contoso.sharepoint.com/sites/finance/Shared%20Documents/quarterly_report.pdf"
  },
  {
    "drive_id": "b!xyz123...",
    "file_id": "01DEF456...",
    "filename": "budget_spreadsheet.xlsx",
    "citation_url": "https://contoso.sharepoint.com/sites/finance/Shared%20Documents/budget_spreadsheet.xlsx"
  }
]
```

### 3. Run the Ingestion

```bash
# Ingest OneDrive files
python ingest_documents.py --onedrive my_files.json

# Continue using local files as before
python ingest_documents.py file.txt
python ingest_documents.py documents_folder/
python ingest_documents.py --sample
```

## API Reference

### Extract Text Function

**Endpoint**: `POST /api/extract_text`

**Headers**:
```
x-functions-key: your_function_key
Content-Type: application/json
```

**Request Body**:
```json
{
  "drive_id": "b!xyz123...",
  "file_id": "01ABC123...",
  "filename": "document.pdf"
}
```

**Response**:
```json
{
  "text": "Extracted text content...",
  "source": "document.pdf",
  "drive_id": "b!xyz123...",
  "file_id": "01ABC123..."
}
```

**Error Response**:
```json
{
  "error": "Error message"
}
```

## Troubleshooting

### Common Issues

1. **Tesseract not found**
   - Solution: Deploy to Linux consumption plan or include Tesseract binaries

2. **Large file timeouts**
   - Solution: Increase function timeout in `host.json` or use premium plan

3. **Memory issues with large PDFs**
   - Solution: Use premium plan with more memory or implement chunked processing

4. **Graph API permissions**
   - Solution: Ensure your app has `Files.Read.All` permission

### Performance Optimization

1. **For heavy OCR workloads**: Consider Azure Container Instances
2. **For large files**: Implement asynchronous processing with Service Bus
3. **For batch processing**: Use the existing `delta_reembed` timer function pattern

## Integration with Existing Workflow

The OneDrive functionality integrates seamlessly with your existing workflow:

1. **Manual ingestion**: Use `ingest_documents.py --onedrive files.json`
2. **Automated ingestion**: Extend `delta_reembed` function to call `extract_text`
3. **Teams bot**: Files shared in Teams can be automatically processed

## Security Considerations

- The `extract_text` function requires function-level authentication
- Microsoft Graph authentication uses your existing app registration
- Files are processed in memory and not stored on disk
- All extracted text is stored in your secured PostgreSQL database

## Next Steps

1. Deploy the updated function app
2. Test with a few sample files
3. Set up automated ingestion for your SharePoint document libraries
4. Monitor function performance and adjust compute resources as needed