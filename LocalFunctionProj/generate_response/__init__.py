import azure.functions as func
import requests
import json
import logging
import os
from retrieve import retrieve_internal

LLM_ENDPOINT_URL = os.getenv("LLM_ENDPOINT_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")

async def generate_response_internal(query: str) -> dict:
    try:
        contexts = await retrieve_internal(query)
        if not contexts:
            return None
        
        context_text = "\n".join([c["content"] for c in contexts])
        citations = [c["citation_url"] for c in contexts if "citation_url"]
        prompt = f"Context: {context_text}\n\nQuestion: {query}\nAnswer:"
        headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
        llm_response = requests.post(f"{LLM_ENDPOINT_URL}/score", json={"input": prompt}, headers=headers)
        if llm_response.status_code != 200:
            logging.error(f"LLM failed: {llm_response.status_code}")
            return None
        
        answer = llm_response.json().get("output", "No response")
        answer_text = f"{answer}\n\nCitations:\n" + "\n".join(citations) if citations else answer
        return {"answer": answer_text}
    except Exception as e:
        logging.error(f"Error in generate_response_internal: {str(e)}")
        return None

async def generate_response(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        query = req_body.get('query')
        response_data = await generate_response_internal(query)
        if response_data:
            return func.HttpResponse(json.dumps(response_data), mimetype="application/json")
        return func.HttpResponse("Failed to generate response", status_code=500)
    except Exception as e:
        logging.error(f"Error in generate_response: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)