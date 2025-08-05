import azure.functions as func
import io
import json
import logging
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
import pandas as pd
from docx import Document
from io import BytesIO
import pdfplumber
from shared.graph_helper import get_graph_client, get_graph_client_personal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_file_type(filename: str) -> str:
    """Determine file type from extension"""
    logger.info(f"Determining file type for file: {filename}")
    extension = filename.lower().split('.')[-1] if '.' in filename else ''
    logger.info(f"File extension: {extension}")
    
    if extension in ['jpg', 'jpeg', 'png', 'tif', 'tiff']:
        return 'image'
    elif extension == 'pdf':
        return 'pdf'
    elif extension in ['xlsx', 'xls']:
        return 'excel'
    elif extension == 'docx':
        return 'word'
    elif extension == 'txt':
        return 'txt'
    elif extension == 'csv':
        return 'csv'
    else:
        return 'Unsupported'

def detect_orientation(image, skip_orientation_check=False):
    """Detect if image is landscape and needs rotation"""
    
    # Skip orientation detection for performance if requested
    if skip_orientation_check:
        logger.info("Skipping orientation detection for performance")
        return image
        
    logger.info("Detecting page orientation")
    
    # Convert image to grayscale for OCR
    gray = image.convert('L')
    
    # Use faster OCR configuration for orientation detection
    fast_config = '--psm 0 --oem 1'  # Page segmentation mode 0 for orientation detection
    
    # Try OCR with current orientation using faster config
    initial_confidence = 0
    try:
        initial_data = pytesseract.image_to_data(gray, config=fast_config, output_type=pytesseract.Output.DICT)
        # Calculate confidence as average confidence of detected words
        if len(initial_data['conf']) > 0:
            valid_confidences = [conf for conf in initial_data['conf'] if conf != -1]
            if valid_confidences:
                initial_confidence = sum(valid_confidences) / len(valid_confidences)
    except Exception as e:
        logger.warning(f"Error in initial OCR attempt: {str(e)}")
        return image
    
    logger.info(f"Initial orientation confidence: {initial_confidence}")
    
    # Lowered threshold for faster processing - if confidence is decent, use it
    if initial_confidence > 30:
        return image
    
    # For very low confidence, only try 90 and 270 degree rotations (most common issues)
    best_confidence = initial_confidence
    best_rotation = 0
    best_image = image
    
    # Only check 90 and 270 degrees for speed
    for angle in [90, 270]:
        rotated = image.rotate(angle, expand=True)
        try:
            rotated_data = pytesseract.image_to_data(rotated.convert('L'), config=fast_config, output_type=pytesseract.Output.DICT)
            if len(rotated_data['conf']) > 0:
                valid_confidences = [conf for conf in rotated_data['conf'] if conf != -1]
                if valid_confidences:
                    confidence = sum(valid_confidences) / len(valid_confidences)
                    logger.info(f"Rotation {angle} degrees confidence: {confidence}")
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_rotation = angle
                        best_image = rotated
        except Exception as e:
            logger.warning(f"Error in rotated OCR attempt at {angle} degrees: {str(e)}")
            continue
    
    logger.info(f"Best rotation found: {best_rotation} degrees with confidence {best_confidence}")
    return best_image

def process_image(image_bytes):
    """Process image bytes and return OCR text"""
    logger.info("Processing image file")
    image = Image.open(io.BytesIO(image_bytes))
    corrected_image = detect_orientation(image)
    return pytesseract.image_to_string(corrected_image).replace('\n', ' ')

def process_pdf(pdf_bytes, max_pages_for_ocr=50):
    """Process PDF by first trying text extraction, then falling back to OCR with limits"""
    logger.info(f"Processing PDF file ({len(pdf_bytes)} bytes)")
    
    # First try to extract text directly from PDF
    try:
        logger.info("Attempting direct text extraction from PDF")
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"PDF has {total_pages} pages")
            
            text_content = []
            for page_num, page in enumerate(pdf.pages):
                logger.info(f"Extracting text from page {page_num + 1}/{total_pages}")
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text.strip())
            
            extracted_text = ' '.join(text_content)
            
            # Check if we extracted meaningful text
            # Consider it text-based if we have at least 50 characters of non-whitespace content
            meaningful_chars = len(''.join(extracted_text.split()))
            logger.info(f"Extracted {meaningful_chars} meaningful characters from PDF")
            
            if meaningful_chars >= 50:
                logger.info("PDF appears to be text-based, using extracted text")
                return extracted_text.replace('\n', ' ')
            else:
                logger.info("PDF appears to have little extractable text, falling back to OCR")
    
    except Exception as e:
        logger.warning(f"Text extraction failed: {str(e)}, falling back to OCR")
    
    # Fall back to OCR if text extraction failed or yielded poor results
    logger.info("Using OCR for PDF processing")
    
    try:
        images = convert_from_bytes(pdf_bytes)
        total_pages = len(images)
        logger.info(f"PDF converted to {total_pages} images for OCR")
        
        # Check if PDF is too large for OCR processing
        if total_pages > max_pages_for_ocr:
            logger.warning(f"PDF has {total_pages} pages, which exceeds the limit of {max_pages_for_ocr} pages for OCR processing")
            logger.info(f"Processing only the first {max_pages_for_ocr} pages")
            images = images[:max_pages_for_ocr]
        
        text_results = []
        skip_orientation = total_pages > 20  # Skip orientation detection for large PDFs
        
        for i, image in enumerate(images):
            logger.info(f"Processing page {i+1}/{len(images)} of PDF with OCR")
            corrected_image = detect_orientation(image, skip_orientation_check=skip_orientation)
            img_byte_arr = io.BytesIO()
            corrected_image.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            text_results.append(process_image(img_byte_arr))
            
            # Progress logging for large files
            if (i + 1) % 10 == 0:
                logger.info(f"OCR progress: {i + 1}/{len(images)} pages completed")
        
        return ' '.join(text_results)
        
    except Exception as e:
        logger.error(f"OCR processing failed: {str(e)}")
        raise e

def process_excel(file_content):
    """Process Excel files"""
    df = pd.read_excel(BytesIO(file_content))
    text_content = df.to_string(index=False)
    return text_content

def process_csv(file_content):
    """Process CSV files"""
    df = pd.read_csv(BytesIO(file_content))
    return df.to_string(index=False)

def process_word(file_content):
    """Process Word documents"""
    doc = Document(BytesIO(file_content))
    text_content = []
    for paragraph in doc.paragraphs:
        if paragraph.text:
            text_content.append(paragraph.text)
    return ' '.join(text_content)

def process_text(file_content):
    """Process text files"""
    # Try different encodings
    encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']
    for encoding in encodings:
        try:
            return file_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    
    # If all encodings fail, use utf-8 with error handling
    return file_content.decode('utf-8', errors='replace')

async def extract_text_from_onedrive_direct(drive_id: str, file_id: str, filename: str) -> str:
    """
    Direct function to extract text from OneDrive files (no HTTP wrapper)
    Returns the extracted text or raises an exception
    """
    try:
        logger.info(f"Processing file: {filename} from drive: {drive_id}")
        
        # Determine file type
        file_type = get_file_type(filename)
        if file_type == 'Unsupported':
            raise ValueError(f'Unsupported file type for {filename}')
        
        logger.info(f"Determined file type: {file_type}")
        
        # Download file from OneDrive using Microsoft Graph
        try:
            logger.info(f"Attempting to download file from OneDrive")
            
            # Try organizational account first
            try:
                logger.info("Trying organizational account authentication...")
                graph_client = await get_graph_client()
                
                # Get file content using the correct API pattern
                file_request = graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(file_id).content
                logger.info(f"File request: {file_request}")
                file_content = await file_request.get()
                # logger.info(f"File content: {file_content}")
                
            except Exception as org_error:
                logger.warning(f"Organizational account failed: {str(org_error)}")
                
                # Check if it's an SPO licensing error (common with personal accounts)
                if "SPO license" in str(org_error) or "BadRequest" in str(org_error) or "DriveRequestBuilder" in str(org_error):
                    logger.info("Trying personal account authentication...")
                    graph_client = await get_graph_client_personal()
                    
                    # For personal accounts, use /me/drive endpoint
                    file_request = graph_client.me.drive.items.by_drive_item_id(file_id).content
                    file_content = await file_request.get()
                else:
                    raise org_error
            
            if not file_content:
                raise Exception("Failed to download file content")
                
            file_bytes = file_content
            logger.info(f"Successfully downloaded file of size: {len(file_bytes)} bytes")
            
        except Exception as e:
            logger.error(f"Error downloading from OneDrive: {str(e)}")
            raise Exception(f'Failed to download file: {str(e)}')

        # Process file based on type
        try:
            if file_type == 'image':
                text = process_image(file_bytes)
            elif file_type == 'pdf':
                text = process_pdf(file_bytes)
            elif file_type == 'excel':
                text = process_excel(file_bytes)
            elif file_type == 'word':
                text = process_word(file_bytes)
            elif file_type == 'txt':
                text = process_text(file_bytes)
            elif file_type == 'csv':
                text = process_csv(file_bytes)
            else:
                raise ValueError('Unsupported file type')
                
            logger.info("Text extraction completed successfully")
            return text
            
        except Exception as e:
            logger.error(f"Error processing file: {str(e)}")
            raise Exception(f'Error processing file: {str(e)}')
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise Exception(f'Unexpected error: {str(e)}')

async def extract_text(req: func.HttpRequest) -> func.HttpResponse:
    """
    Azure Function to extract text from OneDrive files
    Expected request body: {
        "drive_id": "string",
        "file_id": "string", 
        "filename": "string"
    }
    """
    try:
        logger.info(f"Received request")
        
        # Parse request body
        req_body = req.get_json()
        if not req_body:
            return func.HttpResponse("Missing request body", status_code=400)
        
        drive_id = req_body.get('drive_id')
        file_id = req_body.get('file_id')
        filename = req_body.get('filename')
        
        if not all([drive_id, file_id, filename]):
            return func.HttpResponse(
                "Missing required parameters: drive_id, file_id, filename", 
                status_code=400
            )
        
        # Use the direct function
        try:
            text = await extract_text_from_onedrive_direct(drive_id, file_id, filename)
            
            return func.HttpResponse(
                json.dumps({
                    'text': text,
                    'source': filename,
                    'drive_id': drive_id,
                    'file_id': file_id
                }),
                status_code=200,
                mimetype="application/json"
            )
            
        except ValueError as e:
            # Handle unsupported file types
            return func.HttpResponse(
                json.dumps({'error': str(e)}),
                status_code=400,
                mimetype="application/json"
            )
        except Exception as e:
            # Handle all other errors
            return func.HttpResponse(
                json.dumps({'error': str(e)}),
                status_code=500,
                mimetype="application/json"
            )
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                'error': f'Unexpected error: {str(e)}'
            }),
            status_code=500,
            mimetype="application/json"
        )