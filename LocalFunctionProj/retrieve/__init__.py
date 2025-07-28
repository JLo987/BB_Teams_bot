import azure.functions as func
import psycopg2
import numpy as np
import json
import logging
import os
from rank_bm25 import BM25Okapi
from shared.model_helper import get_sentence_model

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

async def retrieve_internal(query: str) -> list:
    try:
        model = get_sentence_model()
        query_embedding = model.encode(query).tolist()

        conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS, sslmode="require")
        cursor = conn.cursor()
        cursor.execute("SELECT id, content, embedding, citation_url FROM chunks ORDER BY embedding <=> %s LIMIT 10", (query_embedding,))
        docs = cursor.fetchall()

        tokenized_docs = [doc[1].split() for doc in docs]
        bm25 = BM25Okapi(tokenized_docs)
        bm25_scores = bm25.get_scores(query.split())

        final_results = []
        for i, (id, content, emb, citation_url) in enumerate(docs):
            cosine_sim = np.dot(query_embedding, emb) / (np.linalg.norm(query_embedding) * np.linalg.norm(emb))
            score = 0.7 * cosine_sim + 0.3 * bm25_scores[i]
            final_results.append({"id": id, "content": content, "score": score, "citation_url": citation_url})
        final_results.sort(key=lambda x: x["score"], reverse=True)

        cursor.close()
        conn.close()
        return final_results[:5]
    except Exception as e:
        logging.error(f"Error in retrieve_internal: {str(e)}")
        return []

async def retrieve(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        query = req_body.get('query')
        results = await retrieve_internal(query)
        return func.HttpResponse(json.dumps(results), mimetype="application/json")
    except Exception as e:
        logging.error(f"Error in retrieve: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)