import azure.functions as func
from embed_function import embed_function
from delta_reembed import delta_reembed
from retrieve import retrieve, retrieve_internal
from generate_response import generate_response, generate_response_internal
from teams_bot import teams_bot
from extract_text import extract_text

app = func.FunctionApp()

# Register HTTP triggered functions
app.route(route="embed_function", auth_level=func.AuthLevel.FUNCTION, methods=["POST"])(embed_function)
app.route(route="teams_bot", auth_level=func.AuthLevel.ANONYMOUS, methods=["POST"])(teams_bot)
app.route(route="retrieve", auth_level=func.AuthLevel.FUNCTION, methods=["POST"])(retrieve)
app.route(route="generate_response", auth_level=func.AuthLevel.FUNCTION, methods=["POST"])(generate_response)
app.route(route="extract_text", auth_level=func.AuthLevel.FUNCTION, methods=["POST"])(extract_text)

# Create wrapper functions for unique naming
async def delta_reembed_timer(timer: func.TimerRequest):
    """Timer-triggered wrapper for delta_reembed"""
    return await delta_reembed(timer)

async def delta_reembed_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered wrapper for delta_reembed"""
    return await delta_reembed(req)

# Register timer triggered function (runs daily at 2 AM)
app.schedule(schedule="0 0 2 * * *", arg_name="timer", run_on_startup=False)(delta_reembed_timer)

# Also register as HTTP function for manual triggering
app.route(route="delta_reembed", auth_level=func.AuthLevel.FUNCTION, methods=["POST"])(delta_reembed_http)