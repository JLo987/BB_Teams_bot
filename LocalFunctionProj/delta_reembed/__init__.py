import azure.functions as func
import psycopg2
import requests
import logging
import os
import json
from shared.graph_helper import get_graph_client

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
EMBED_FUNCTION_URL = os.getenv("EMBED_FUNCTION_URL")
GRAPH_SITE_ID = os.getenv("GRAPH_SITE_ID")
GRAPH_DELTA_LINK = os.getenv("GRAPH_DELTA_LINK")

# async def delta_reembed(timer: func.TimerInfo) -> None:
async def delta_reembed() -> None:
    try:
        graph_client = await get_graph_client()
        delta_request = graph_client.sites.by_site_id(GRAPH_SITE_ID).drive.root.delta
        if GRAPH_DELTA_LINK:
            delta_request = delta_request.get(delta_link=GRAPH_DELTA_LINK)
        delta = await delta_request.get()
        changes = delta.value
        new_delta_link = delta.additional_data.get('@odata.deltaLink')
        logging.info(f"New delta link: {new_delta_link}")

        conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS, sslmode="require")
        cursor = conn.cursor()

        for change in changes:
            if change.file:
                content_response = await graph_client.drives.by_drive_id(change.parent_reference.drive_id).items.by_drive_item_id(change.id).content.get()
                content = content_response.value.decode('utf-8') if content_response else ''
                response = requests.post(EMBED_FUNCTION_URL, json={"text": content})
                if response.status_code == 200:
                    embedding = response.json()
                    cursor.execute("""
                        INSERT INTO chunks (content, embedding, metadata, citation_url, source_id)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (source_id) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata, citation_url = EXCLUDED.citation_url
                    """, (content, embedding, json.dumps({"last_modified": change.last_modified_date_time}), change.web_url, change.id))
                    conn.commit()
                    logging.info(f"Re-embedded chunk {change.id}")
                else:
                    logging.error(f"Failed to embed chunk {change.id}: {response.status_code}")

        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error in delta_reembed: {str(e)}")