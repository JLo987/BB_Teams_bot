import azure.functions as func
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import json
import logging
import os
from generate_response import generate_response_internal

APP_ID = os.getenv("MicrosoftAppId")
APP_PASSWORD = os.getenv("MicrosoftAppPassword")
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)

async def handle_message(turn_context: TurnContext):
    if turn_context.activity.type == "message":
        query = turn_context.activity.text
        try:
            response_data = await generate_response_internal(query)
            if response_data:
                await turn_context.send_activity(response_data.get("answer", "No response"))
            else:
                await turn_context.send_activity("Sorry, couldn't process your query.")
        except Exception as e:
            logging.error(f"Error in handle_message: {str(e)}")
            await turn_context.send_activity("Error occurred. Try again.")

class RagBot:
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.type == "message":
            await handle_message(turn_context)

BOT = RagBot()

async def teams_bot(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        response = await adapter.process_activity(activity, auth_header, BOT.on_turn)
        if response:
            return func.HttpResponse(json.dumps(response.body), status_code=response.status, mimetype="application/json")
        return func.HttpResponse(status_code=201)
    except Exception as e:
        logging.error(f"Error in teams_bot: {str(e)}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=400)