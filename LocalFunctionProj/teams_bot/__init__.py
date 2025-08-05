import azure.functions as func
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
import json
import logging
import os
from generate_response import generate_response_with_context
from shared.conversation_helper import conversation_manager

APP_ID = os.getenv("MicrosoftAppId")
APP_PASSWORD = os.getenv("MicrosoftAppPassword")
APP_TENANT_ID = os.getenv("MicrosoftAppTenantId")

# For Bot Emulator local testing, allow empty credentials
if not APP_ID and not APP_PASSWORD:
    logging.info("Running in local emulator mode without authentication")
    adapter_settings = BotFrameworkAdapterSettings("", "")
else:
    # Configure for cross-tenant hosting scenario
    # Bot App Registration is in target organization, but hosting is in different Azure account
    logging.info(f"Configuring bot for cross-tenant hosting")
    logging.info(f"- App ID: {APP_ID[:8]}...")
    logging.info(f"- Target tenant: {APP_TENANT_ID}")
    
    # Configure adapter settings for single-tenant cross-hosting scenario
    adapter_settings = BotFrameworkAdapterSettings(
        app_id=APP_ID, 
        app_password=APP_PASSWORD
    )
    
    # For single-tenant bots, we may need to explicitly set the OAuth scope
    # This helps with cross-tenant hosting scenarios
    if APP_TENANT_ID:
        logging.info(f"Configuring OAuth scope for tenant: {APP_TENANT_ID}")
        # The Bot Framework will validate against the tenant where the app is registered
    
    # The Bot Framework will validate tokens against the tenant where the App Registration exists
    # This works even when the Azure Function is hosted in a different Azure account

adapter = BotFrameworkAdapter(adapter_settings)

async def handle_message(turn_context: TurnContext):
    """Handle incoming messages with conversation context"""
    if turn_context.activity.type == "message":
        user_message = turn_context.activity.text
        user_id = turn_context.activity.from_property.id
        conversation_id = turn_context.activity.conversation.id
        channel_id = getattr(turn_context.activity, 'channel_id', None)
        message_id = turn_context.activity.id
        
        try:
            # Get or create conversation tracking
            conversation_uuid = conversation_manager.get_or_create_conversation(
                teams_conversation_id=conversation_id,
                user_id=user_id,
                channel_id=channel_id
            )
            
            if not conversation_uuid:
                await turn_context.send_activity("Sorry, I'm having trouble tracking our conversation. Please try again.")
                return
            
            # Store the user message
            conversation_manager.add_message(
                conversation_uuid=conversation_uuid,
                role='user',
                content=user_message,
                message_id=message_id
            )
            
            # Get conversation context for the LLM
            conversation_context = conversation_manager.get_conversation_context(
                teams_conversation_id=conversation_id,
                user_id=user_id,
                limit=6  # Last 6 messages (3 exchanges)
            )
            
            # Generate response with context and user permissions
            response_data = await generate_response_with_context(
                query=user_message,
                conversation_context=conversation_context,
                user_id=user_id
            )
            
            if response_data and response_data.get("answer"):
                bot_response = response_data["answer"]
                
                # Store the bot response
                conversation_manager.add_message(
                    conversation_uuid=conversation_uuid,
                    role='assistant',
                    content=bot_response
                )
                
                # Send response to user
                try:
                    await turn_context.send_activity(bot_response)
                except Exception as send_error:
                    # In local testing, sending responses might fail due to mock service URLs
                    logging.warning(f"Failed to send response (likely local testing): {str(send_error)}")
                    # Don't crash the bot if response sending fails in local testing
                
                # Cleanup old messages if conversation is getting long
                conversation_manager.cleanup_old_messages(conversation_uuid, keep_last=20)
                
            else:
                error_response = "Sorry, I couldn't process your question right now. Please try again."
                try:
                    await turn_context.send_activity(error_response)
                except Exception as send_error:
                    logging.warning(f"Failed to send error response (likely local testing): {str(send_error)}")
                
                # Store error response for context
                conversation_manager.add_message(
                    conversation_uuid=conversation_uuid,
                    role='assistant',
                    content=error_response
                )
                
        except Exception as e:
            logging.error(f"Error in handle_message: {str(e)}")
            error_response = "An error occurred while processing your message. Please try again."
            try:
                await turn_context.send_activity(error_response)
            except Exception as send_error:
                logging.warning(f"Failed to send error response (likely local testing): {str(send_error)}")
            
            # Try to store error response
            try:
                if 'conversation_uuid' in locals():
                    conversation_manager.add_message(
                        conversation_uuid=conversation_uuid,
                        role='assistant',
                        content=error_response
                    )
            except:
                pass  # Don't fail if we can't store the error message

async def handle_members_added(turn_context: TurnContext):
    """Handle when members are added to the conversation"""
    welcome_message = """👋 Hello! I'm your RAG bot assistant. 

I can help answer questions using our knowledge base. Just ask me anything, and I'll:
• Search through our documents to find relevant information
• Provide answers with source citations
• Remember our conversation context for follow-up questions

Try asking me something like:
• "What is Azure Functions?"
• "How do Teams bots work?"
• "Tell me about RAG systems"

How can I help you today?"""
    
    for member in turn_context.activity.members_added:
        if member.id != turn_context.activity.recipient.id:
            try:
                await turn_context.send_activity(welcome_message)
            except Exception as send_error:
                logging.warning(f"Failed to send welcome message (likely local testing): {str(send_error)}")

class RagBot:
    async def on_turn(self, turn_context: TurnContext):
        """Main bot turn handler"""
        if turn_context.activity.type == "message":
            await handle_message(turn_context)
        elif turn_context.activity.type == "membersAdded":
            await handle_members_added(turn_context)
        elif turn_context.activity.type == "conversationUpdate":
            # Handle conversation updates (like when emulator connects)
            logging.info("Conversation update received - bot is ready")
            # No response needed for conversationUpdate
        else:
            # Handle other activity types if needed
            logging.info(f"Received activity type: {turn_context.activity.type}")
            # No response needed for unknown activity types

BOT = RagBot()

async def teams_bot(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        if not body:
            logging.error("No JSON body received")
            return func.HttpResponse("No JSON body provided", status_code=400)
            
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        
        # Enhanced logging for authentication debugging
        if auth_header:
            logging.info("Processing activity with authorization header")
            # Log partial auth header for debugging (safely)
            if auth_header.startswith("Bearer "):
                token_preview = auth_header[:20] + "..." if len(auth_header) > 20 else auth_header
                logging.info(f"Auth header preview: {token_preview}")
        else:
            logging.info("Processing activity without authorization header (local emulator mode)")
        
        # Log activity details for debugging
        logging.info(f"Activity type: {activity.type}, Channel: {getattr(activity, 'channel_id', 'unknown')}")
        if hasattr(activity, 'from_property') and activity.from_property:
            logging.info(f"From: {getattr(activity.from_property, 'id', 'unknown')}")
        
        response = await adapter.process_activity(activity, auth_header, BOT.on_turn)
        
        if response:
            return func.HttpResponse(
                json.dumps(response.body), 
                status_code=response.status, 
                mimetype="application/json"
            )
        return func.HttpResponse(status_code=200)
        
    except ValueError as e:
        logging.error(f"JSON parsing error in teams_bot: {str(e)}")
        return func.HttpResponse(f"Invalid JSON: {str(e)}", status_code=400)
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Error in teams_bot: {error_msg}")
        
        # Enhanced error handling for authentication issues
        if "Unauthorized" in error_msg or "No valid identity" in error_msg:
            logging.error("Cross-Tenant Hosting Authentication Error:")
            logging.error(f"- App ID configured: {bool(APP_ID)}")
            logging.error(f"- App Password configured: {bool(APP_PASSWORD)}")
            logging.error(f"- Target tenant: {APP_TENANT_ID}")
            logging.error("- Bot App Registration should be in the target organization")
            logging.error("- Azure Function hosting account can be different")
            logging.error("- Verify Bot App Registration exists and credentials are correct")
            logging.error("- Ensure Bot Service messaging endpoint points to this function")
            
            return func.HttpResponse(
                "Authentication failed. Verify Bot App Registration in target organization and messaging endpoint configuration.", 
                status_code=401
            )
        
        return func.HttpResponse(f"Error: {error_msg}", status_code=500)