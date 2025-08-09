import azure.functions as func
import requests
import json
import logging
import os
from retrieve import retrieve_internal

LLM_ENDPOINT_URL = os.getenv("LLM_ENDPOINT_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # huggingface, azure_openai, ollama, anthropic

async def call_llm(prompt: str) -> str:
    """Call LLM based on configured provider"""
    try:
        if LLM_PROVIDER == "azure_openai":
            return await call_azure_openai(prompt)
        elif LLM_PROVIDER == "ollama":
            return await call_ollama(prompt)
        elif LLM_PROVIDER == "anthropic":
            return await call_anthropic(prompt)
        else:  # default to huggingface
            return await call_huggingface(prompt)
    except Exception as e:
        logging.error(f"LLM call failed: {str(e)}")
        return "Sorry, I couldn't generate a response right now."

async def call_anthropic(prompt: str) -> str:
    """Call Anthropic Claude API with lazy import"""
    try:
        # Lazy import to reduce startup time
        import anthropic
        
        client = anthropic.Anthropic(api_key=LLM_API_KEY)
        
        message = client.messages.create(
            model="claude-3-haiku-20240307",  # You can also use claude-3-sonnet-20240229 or claude-3-opus-20240229
            max_tokens=500,
            temperature=0.1,
            system="You are a helpful assistant. Answer questions based on the provided context. If you don't have enough information to answer properly, please say so clearly.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text
        
    except Exception as e:
        logging.error(f"Anthropic API error: {str(e)}")
        return "Error calling Anthropic API"

async def call_azure_openai(prompt: str) -> str:
    """Call Azure OpenAI API"""
    headers = {
        "api-key": LLM_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Answer questions based on the provided context and conversation history."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.1
    }
    
    response = requests.post(f"{LLM_ENDPOINT_URL}/openai/deployments/gpt-35-turbo/chat/completions?api-version=2023-12-01-preview", 
                           json=data, headers=headers, timeout=30)
    
    if response.status_code == 200:
        result = response.json()
        return result["choices"][0]["message"]["content"]
    else:
        logging.error(f"Azure OpenAI error: {response.status_code} - {response.text}")
        return "Error calling Azure OpenAI"

async def call_huggingface(prompt: str) -> str:
    """Call Hugging Face Inference API"""
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    data = {"inputs": prompt, "parameters": {"max_new_tokens": 500, "temperature": 0.1}}
    logging.info(f"Hugging Face data: {data}")
    logging.info(f"Hugging Face headers: {headers}")
    logging.info(f"Hugging Face endpoint: {LLM_ENDPOINT_URL}")
    logging.info(f"Hugging Face prompt: {prompt}")
    
    response = requests.post(LLM_ENDPOINT_URL, json=data, headers=headers, timeout=30)
    
    if response.status_code == 200:
        result = response.json()
        if isinstance(result, list) and len(result) > 0:
            return result[0].get("generated_text", "").replace(prompt, "").strip()
        return str(result)
    else:
        logging.error(f"Hugging Face error: {response.status_code} - {response.text}")
        return "Error calling Hugging Face API"

async def call_ollama(prompt: str) -> str:
    """Call local Ollama API"""
    data = {
        "model": "phi3:mini",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 500}
    }
    
    response = requests.post(f"{LLM_ENDPOINT_URL}/api/generate", json=data, timeout=60)
    
    if response.status_code == 200:
        result = response.json()
        return result.get("response", "No response generated")
    else:
        logging.error(f"Ollama error: {response.status_code} - {response.text}")
        return "Error calling local LLM"

async def generate_response_with_context(query: str, conversation_context: str = "", user_id: str = None) -> dict:
    """Generate response with conversation context and user permissions"""
    try:
        # Retrieve relevant contexts (filtered by user permissions)
        contexts = await retrieve_internal(query, user_id)
        if not contexts:
            # If no documents found, still try to answer based on conversation context
            if conversation_context:
                prompt = f"""Previous conversation:
{conversation_context}

Current question: {query}

Based on our conversation history, please provide a helpful response. If you don't have enough information to answer properly, please say so clearly."""
            else:
                return {"answer": "I couldn't find relevant information to answer your question. Could you provide more details or try rephrasing your question?"}
        else:
            # Prepare context and citations
            context_text = "\n".join([c["content"] for c in contexts[:3]])  # Limit to top 3 contexts
            filenames = [c["filename"] for c in contexts[:3]]
            # Deduplicate citations while preserving order
            citations = []
            seen_citations = set()
            for c in contexts[:3]:
                if c.get("citation_url") and c["citation_url"] not in seen_citations:
                    citations.append(c["citation_url"])
                    seen_citations.add(c["citation_url"])
            
            # Create prompt with conversation history
            if conversation_context:
                prompt = f"""Previous conversation:
{conversation_context}

Context information from knowledge base:
{context_text}

Current question: {query}

Based on both the conversation history and the context information provided above, please answer the current question. Be conversational and refer to our previous discussion when relevant. If the context doesn't contain enough information to answer the question, say so clearly."""
            else:
                prompt = f"""Context information from knowledge base:
{context_text}

Question: {query}

Based on the context provided above, please answer the question. If the context doesn't contain enough information to answer the question, say so clearly."""
        
        # Get LLM response
        answer = await call_llm(prompt)
        
        # Add citations if available
        if 'citations' in locals() and citations:
            # Map citation_url to a set of filenames (to deduplicate by citation)
            citation_map = {}
            for c in contexts[:3]:
                citation_url = c.get('citation_url')
                filename = c.get('filename', 'Document')
                if citation_url:
                    if citation_url in citation_map:
                        citation_map[citation_url].add(filename)
                    else:
                        citation_map[citation_url] = set([filename])
            
            citation_links = []
            for citation_url, filenames in citation_map.items():
                filenames_str = ", ".join(sorted(filenames))
                citation_links.append(f"• [{filenames_str}]({citation_url})")
            
            citation_text = "\n\nSources:\n" + "\n".join(citation_links)
            answer += citation_text
        
        return {"answer": answer}
        
    except Exception as e:
        logging.error(f"Error in generate_response_with_context: {str(e)}")
        return {"answer": "Sorry, I encountered an error while processing your request."}

async def generate_response_internal(query: str, user_id: str = None) -> dict:
    """Original function for backwards compatibility"""
    return await generate_response_with_context(query, "", user_id)

async def generate_response(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        query = req_body.get('query')
        conversation_context = req_body.get('conversation_context', "")
        user_id = req_body.get('user_id')  # Optional user_id for permission filtering
        logging.info(f"Query: {query}")
        logging.info(f"Conversation context: {conversation_context}")
        logging.info(f"User ID: {user_id}")
        
        if not query:
            return func.HttpResponse("Missing 'query' in request body", status_code=400)
        
        response_data = await generate_response_with_context(query, conversation_context, user_id)
        logging.info(f"Response data: {response_data}")
        return func.HttpResponse(json.dumps(response_data), mimetype="application/json")
        
    except Exception as e:
        logging.error(f"Error in generate_response: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)