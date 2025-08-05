import azure.functions as func
import json
import logging
from shared.model_helper import get_sentence_model
from typing import List

def get_embedding_direct(text: str) -> List[float]:
    """
    Direct function to get embeddings for text (no HTTP wrapper)
    Returns the embedding vector or raises an exception
    """
    try:
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        model = get_sentence_model()
        embedding = model.encode(text).tolist()
        return embedding
        
    except Exception as e:
        logging.error(f"Error getting embedding: {str(e)}")
        raise Exception(f"Error getting embedding: {str(e)}")

async def embed_function(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        text = req_body.get('text')
        if not text:
            return func.HttpResponse("Missing text", status_code=400)
        
        # Use the direct function
        embedding = get_embedding_direct(text)
        return func.HttpResponse(json.dumps(embedding), mimetype="application/json")
        
    except ValueError as e:
        # Handle validation errors
        return func.HttpResponse(str(e), status_code=400)
    except Exception as e:
        logging.error(f"Error in embed_function: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)