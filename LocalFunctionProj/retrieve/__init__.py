import azure.functions as func
import psycopg2
import json
import logging
import os
from shared.model_helper import get_sentence_model

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

async def retrieve_internal(query: str, user_id: str = None, user_email: str = None) -> list:
    """Retrieve documents using optimized vector similarity and BM25 scoring, filtered by user permissions."""
    try:
        # Validate input
        if not query or not query.strip():
            return []
        
        # Get query embedding
        model = get_sentence_model()
        query_embedding = model.encode(query).tolist()
        
        # Connect to database
        conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, 
            user=DB_USER, password=DB_PASS, sslmode="require"
        )
        cursor = conn.cursor()
        
        # Format embedding as PostgreSQL vector
        query_vector_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        if user_id:
            # Use optimized search function with permission filtering
            cursor.execute("""
                SELECT id, content, embedding, filename, citation_url, similarity_score
                FROM search_chunks_with_permissions(%s::vector, %s, %s, 10)
            """, (query_vector_str, user_id, user_email))
            
            # Get results from optimized function
            docs = cursor.fetchall()
            logging.info(f"Permission-filtered docs from optimized function: {len(docs)} results")
            
        else:
            # Fallback query using optimized table structure (for testing or anonymous access)
            logging.warning("No user_id provided for permission filtering - returning all results")
            cursor.execute("""
                SELECT id, content, embedding, filename, citation_url, 
                       1 - (embedding <=> %s::vector) as similarity_score
                FROM chunks 
                WHERE word_count > 10
                ORDER BY embedding <=> %s::vector 
                LIMIT 10
            """, (query_vector_str, query_vector_str))
            docs = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        if not docs:
            return []
        
        # Prepare documents for BM25 scoring
        valid_docs = []
        tokenized_docs = []
        
        for doc in docs:
            content = doc[1].strip() if doc[1] else ""
            if content:
                tokens = content.split()
                if tokens:
                    valid_docs.append(doc)
                    tokenized_docs.append(tokens)
        
        if not tokenized_docs:
            return []
        
        # Calculate BM25 scores for hybrid ranking (lazy import)
        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi(tokenized_docs)
        query_tokens = query.strip().split()
        bm25_scores = bm25.get_scores(query_tokens) if query_tokens else [0.0] * len(tokenized_docs)
        
        # Combine vector similarity and BM25 scores
        final_results = []
        
        for i, (doc_id, content, embedding, filename, citation_url, similarity_score) in enumerate(valid_docs):
            # Combine scores (70% vector similarity, 30% BM25)
            # similarity_score is already calculated by the database function
            combined_score = 0.7 * similarity_score + 0.3 * bm25_scores[i]
            
            final_results.append({
                "id": doc_id,
                "content": content,
                "score": float(combined_score),
                "citation_url": citation_url,
                "filename": filename or 'Document'
            })
        
        # Sort by combined score and return top 5
        final_results.sort(key=lambda x: x["score"], reverse=True)
        logging.info(f"Final results: {len(final_results)} documents")
        return final_results[:5]
        
    except Exception as e:
        logging.error(f"Error in retrieve_internal: {str(e)}")
        return []
async def retrieve(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        query = req_body.get('query')
        user_id = req_body.get('user_id')  # Optional user_id for permission filtering
        user_email = req_body.get('user_email')  # Optional user_email for permission filtering
        results = await retrieve_internal(query, user_id, user_email)
        return func.HttpResponse(json.dumps(results), mimetype="application/json")
    except Exception as e:
        logging.error(f"Error in retrieve: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)