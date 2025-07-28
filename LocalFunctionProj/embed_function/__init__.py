import azure.functions as func
import json
import logging
from shared.model_helper import get_sentence_model

async def embed_function(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        text = req_body.get('text')
        if not text:
            return func.HttpResponse("Missing text", status_code=400)
        
        model = get_sentence_model()
        embedding = model.encode(text).tolist()
        return func.HttpResponse(json.dumps(embedding), mimetype="application/json")
    except Exception as e:
        logging.error(f"Error in embed_function: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)