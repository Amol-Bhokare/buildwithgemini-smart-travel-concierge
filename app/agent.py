import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from dotenv import load_dotenv
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

load_dotenv()

# HARDCODED STRINGS (Required: Agent Platform returns project number for GOOGLE_CLOUD_PROJECT)
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-4ae329ac7f7f"
GCS_BUCKET_NAME = "smart-travel-concierge-media-4ae329"

# Load remote Agent Engine resource ID from deployment_metadata.json if present
DEPLOYMENT_METADATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "deployment_metadata.json"
)

remote_agent_runtime_id = None
if os.path.exists(DEPLOYMENT_METADATA_PATH):
    try:
        with open(DEPLOYMENT_METADATA_PATH, "r") as f:
            meta = json.load(f)
            remote_agent_runtime_id = meta.get("remote_agent_runtime_id")
    except Exception:
        pass

code_executor = None
if remote_agent_runtime_id:
    code_executor = AgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=remote_agent_runtime_id
    )

# MEMORY BANK CONFIGURATION
MEMORY_BANK_ID = "948156705387053056"
memory_service = VertexAiMemoryBankService(
    project=FIRESTORE_PROJECT_ID,
    location="us-central1",
    agent_engine_id=MEMORY_BANK_ID,
)


async def generate_memories_callback(callback_context: CallbackContext):
    """Sends session turn events to Vertex AI Memory Bank for long-term memory extraction."""
    await callback_context.add_session_to_memory()
    return None


def get_firestore_client():
    """Initializes and returns a Firestore client with the hardcoded project ID."""
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def list_destinations(category: str = "") -> list[dict]:
    """Reads travel destinations from Firestore.

    Args:
        category: Optional category filter (e.g. 'Cultural', 'Beach & Island', 'Nature & Adventure', 'Art & Culinary'). If empty, returns all destinations.

    Returns:
        A list of destination dictionaries.
    """
    db = get_firestore_client()
    collection_ref = db.collection("destinations")
    if category:
        docs = collection_ref.where("category", "==", category).stream()
    else:
        docs = collection_ref.stream()

    results = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        results.append(data)
    return results


def add_destination(
    doc_id: str,
    name: str,
    country: str,
    category: str,
    description: str,
    rating: float = 4.5,
    best_season: str = "All Year",
    estimated_cost_per_day_usd: int = 150,
) -> dict:
    """Adds a new travel destination to the Firestore database.

    Args:
        doc_id: Unique string identifier for the destination (e.g. 'paris').
        name: Name of the destination (e.g. 'Paris City of Lights').
        country: Country where destination is located (e.g. 'France').
        category: Theme/category (e.g. 'Cultural', 'Art & Culinary', 'Nature & Adventure').
        description: Brief highlights and summary.
        rating: Overall rating score (1.0 to 5.0).
        best_season: Best time of year to visit.
        estimated_cost_per_day_usd: Estimated average daily cost in USD.

    Returns:
        A dictionary confirming the destination was saved.
    """
    db = get_firestore_client()
    doc_data = {
        "id": doc_id,
        "name": name,
        "country": country,
        "category": category,
        "description": description,
        "rating": float(rating),
        "best_season": best_season,
        "estimated_cost_per_day_usd": int(estimated_cost_per_day_usd),
    }
    db.collection("destinations").document(doc_id).set(doc_data)
    return {"status": "success", "destination": doc_data}


def get_destination_details(doc_id: str) -> dict:
    """Fetches details for a specific destination from Firestore by document ID.

    Args:
        doc_id: The document ID of the destination (e.g. 'kyoto', 'santorini', 'banff').

    Returns:
        Dictionary containing destination details or an error message if not found.
    """
    db = get_firestore_client()
    doc = db.collection("destinations").document(doc_id).get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return {"error": f"Destination with ID '{doc_id}' not found."}


def get_weather(query: str) -> str:
    """Simulates getting current weather for a travel destination.

    Args:
        query: Destination or city name.

    Returns:
        Weather report.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    elif "kyoto" in query.lower() or "japan" in query.lower():
        return "It's 68 degrees and sunny with a gentle breeze."
    elif "santorini" in query.lower() or "greece" in query.lower():
        return "It's 78 degrees and clear sky."
    return "It's 72 degrees and pleasant."


def calculate_trip_budget(
    daily_cost_usd: float,
    duration_days: int = 1,
    num_travelers: int = 1,
    target_currency: str = "USD",
) -> dict:
    """Calculates total estimated trip budget, per-person costs, and optional currency conversion.

    Args:
        daily_cost_usd: Estimated average daily cost per person in USD.
        duration_days: Length of trip in days.
        num_travelers: Number of people traveling.
        target_currency: Target currency code (e.g. 'USD', 'EUR', 'JPY', 'GBP', 'CAD').

    Returns:
        Dictionary containing total budget, cost per person, currency, and detailed summary.
    """
    rates = {
        "USD": 1.0,
        "EUR": 0.92,
        "JPY": 155.0,
        "GBP": 0.79,
        "CAD": 1.36,
    }
    currency = target_currency.upper()
    rate = rates.get(currency, 1.0)

    total_usd = float(daily_cost_usd) * int(duration_days) * int(num_travelers)
    total_converted = round(total_usd * rate, 2)
    per_person_converted = round(
        total_converted / max(1, int(num_travelers)), 2
    )

    return {
        "duration_days": int(duration_days),
        "num_travelers": int(num_travelers),
        "daily_cost_usd": float(daily_cost_usd),
        "target_currency": currency,
        "total_budget": total_converted,
        "per_person_budget": per_person_converted,
        "summary": f"{duration_days} days for {num_travelers} traveler(s) at ${daily_cost_usd:.2f} USD/day = {total_converted} {currency} total ({per_person_converted} {currency} per person).",
    }


def get_live_destination_info(destination_name: str) -> dict:
    """Fetches real-time geographic data, timezone, population, coordinates, and live weather forecast for a destination using Open-Meteo public API.

    Args:
        destination_name: The name of the city or destination (e.g. 'Kyoto', 'Santorini', 'Paris', 'Banff').

    Returns:
        Dictionary containing country, latitude, longitude, timezone, population, live temperature_celsius, and windspeed.
    """
    encoded_name = urllib.parse.quote(destination_name)
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_name}&count=1&language=en&format=json"

    # Support optional environment variable for API key if provided
    api_key = os.getenv("OPEN_METEO_API_KEY", "")
    if api_key:
        geo_url += f"&apikey={api_key}"

    headers = {"User-Agent": "SmartTravelConcierge/1.0"}

    try:
        req = urllib.request.Request(geo_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            geo_data = json.loads(resp.read().decode())

        results = geo_data.get("results")
        if not results:
            return {"error": f"Could not find geographic location for '{destination_name}'."}

        city_info = results[0]
        lat = city_info.get("latitude")
        lon = city_info.get("longitude")

        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        if api_key:
            weather_url += f"&apikey={api_key}"

        w_req = urllib.request.Request(weather_url, headers=headers)
        with urllib.request.urlopen(w_req, timeout=5) as w_resp:
            weather_data = json.loads(w_resp.read().decode())

        current_w = weather_data.get("current_weather", {})

        return {
            "destination": city_info.get("name"),
            "country": city_info.get("country", "Unknown"),
            "latitude": lat,
            "longitude": lon,
            "timezone": city_info.get("timezone", "UTC"),
            "population": city_info.get("population", 0),
            "temperature_celsius": current_w.get("temperature"),
            "windspeed_kmh": current_w.get("windspeed"),
            "is_daytime": bool(current_w.get("is_day", 1)),
        }
    except Exception as e:
        return {"error": f"Failed to fetch live destination info: {str(e)}"}


def geocode_address(address: str) -> dict:
    """Uses Google Maps Geocoding API to convert an address or place name into geographic coordinates.

    Args:
        address: Address or landmark name (e.g. 'Eiffel Tower, Paris' or 'Kyoto Station').

    Returns:
        Dictionary with name, address, and location (latitude, longitude).
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY environment variable is not set."}

    encoded = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded}&key={api_key}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") != "OK" or not data.get("results"):
            return {"error": f"Geocoding failed for '{address}': {data.get('status')}"}

        result = data["results"][0]
        location = result["geometry"]["location"]
        return {
            "name": address,
            "address": result.get("formatted_address"),
            "location": {
                "latitude": location.get("lat"),
                "longitude": location.get("lng"),
            },
        }
    except Exception as e:
        return {"error": f"Geocoding request error: {str(e)}"}


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "tourist_attraction",
    radius_meters: float = 1000.0,
) -> dict:
    """Uses Google Places API (New) searchNearby endpoint to find nearby places of a given type around coordinates.

    Args:
        latitude: Center latitude coordinate.
        longitude: Center longitude coordinate.
        place_type: Type of place to search for (e.g. 'restaurant', 'cafe', 'tourist_attraction', 'museum', 'hotel').
        radius_meters: Radius in meters around the center point (default: 1000.0).

    Returns:
        Dictionary containing list of nearby places with name, address, and location.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY environment variable is not set."}

    url = "https://places.googleapis.com/v1/places:searchNearby"
    payload = json.dumps({
        "includedTypes": [place_type],
        "maxResultCount": 10,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                },
                "radius": float(radius_meters),
            }
        },
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }

    try:
        req = urllib.request.Request(
            url, data=payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        places_list = []
        for p in data.get("places", []):
            display_name = p.get("displayName", {}).get("text", "Unknown")
            loc = p.get("location", {})
            places_list.append({
                "name": display_name,
                "address": p.get("formattedAddress"),
                "location": {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                },
            })

        return {
            "center": {"latitude": latitude, "longitude": longitude},
            "place_type": place_type,
            "places_count": len(places_list),
            "places": places_list,
        }
    except Exception as e:
        return {"error": f"Places API request error: {str(e)}"}


def generate_destination_image(
    prompt: str,
    destination_name: str = "destination",
    tool_context: ToolContext = None,
) -> dict:
    """Generates a scenic travel artwork/photo for a destination using gemini-3.1-flash-lite-image in the global region.
    Saves the image as an ADK artifact for Playground display and uploads it directly to public Cloud Storage.

    Args:
        prompt: Description of the destination image to generate (e.g. 'A scenic sunset view over Santorini white cliffside houses').
        destination_name: Name or ID of the destination (e.g. 'santorini', 'kyoto').
        tool_context: ADK ToolContext instance provided automatically by the agent runtime.

    Returns:
        Dictionary containing status, artifact filename, and public Cloud Storage URL.
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )

        res = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
        )

        if not res.candidates or not res.candidates[0].content.parts:
            return {"error": "No image generated by model."}

        part = res.candidates[0].content.parts[0]
        inline_data = getattr(part, "inline_data", None)
        if not inline_data or not inline_data.data:
            return {"error": "Generated content did not contain inline image bytes."}

        image_bytes = inline_data.data
        mime_type = inline_data.mime_type or "image/jpeg"
        ext = "jpg" if "jpeg" in mime_type.lower() else "png"

        timestamp = int(datetime.datetime.now().timestamp())
        clean_name = destination_name.lower().replace(" ", "_")
        filename = f"{clean_name}_{timestamp}.{ext}"

        # (1) Save artifact in ADK tool_context (Playground Artifacts panel)
        if tool_context:
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # (2) Upload directly from memory bytes to public GCS bucket
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "destination_name": destination_name,
            "filename": filename,
            "public_url": public_url,
        }
    except Exception as e:
        return {"error": f"Image generation failed: {str(e)}"}


def generate_destination_video(
    prompt: str,
    destination_name: str = "destination",
    tool_context: ToolContext = None,
) -> dict:
    """Generates a short travel video for a destination or item using gemini-omni-flash-preview in the global region.
    Saves the video as an ADK artifact for Playground display and uploads it directly to public Cloud Storage.

    Args:
        prompt: Description of the video to generate (e.g. 'A scenic drone video of Kyoto cherry blossoms in spring').
        destination_name: Name or identifier of the destination (e.g. 'kyoto', 'santorini').
        tool_context: ADK ToolContext instance provided automatically by the agent runtime.

    Returns:
        Dictionary containing status, filename, and public Cloud Storage URL (https://storage.googleapis.com/<bucket>/<object>).
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )

        interaction = genai_client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(interaction, "output_video") and interaction.output_video and getattr(interaction.output_video, "data", None):
            raw_data = interaction.output_video.data
            video_bytes = base64.b64decode(raw_data) if isinstance(raw_data, str) else raw_data
        elif hasattr(interaction, "steps") and interaction.steps:
            for step in interaction.steps:
                if getattr(step, "type", "") == "model_output":
                    for content in getattr(step, "content", []):
                        if getattr(content, "type", "") == "video" or hasattr(content, "data"):
                            raw_data = getattr(content, "data", None)
                            if raw_data:
                                video_bytes = base64.b64decode(raw_data) if isinstance(raw_data, str) else raw_data
                                if hasattr(content, "mime_type"):
                                    mime_type = content.mime_type
                                break

        if not video_bytes:
            return {"error": "No video content returned by gemini-omni-flash-preview."}

        timestamp = int(datetime.datetime.now().timestamp())
        clean_name = destination_name.lower().replace(" ", "_")
        filename = f"{clean_name}_{timestamp}.mp4"

        # (1) Save artifact in ADK tool_context (Playground Artifacts panel)
        if tool_context:
            artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # (2) Upload directly from memory bytes to public GCS bucket
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "destination_name": destination_name,
            "filename": filename,
            "public_url": public_url,
        }
    except Exception as e:
        return {"error": f"Video generation failed: {str(e)}"}


# A2UI SCHEMA MANAGER SYSTEM PROMPT (VERSION 0.8)
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Smart Travel Concierge, an AI assistant helping users explore destinations, geocode locations, search nearby attractions/restaurants, generate destination imagery, execute Python code for travel analytics or calculations, calculate travel budgets, and plan custom trips. "
        "You remember all user travel preferences, allergies, dietary restrictions, and health/medical requirements across sessions and proactively filter recommendations (e.g. dining, food, activities) to keep the user safe. "
        "Always remember and account for any user allergies mentioned (e.g., peanuts, gluten, shellfish, dairy) in all future sessions and recommendations. "
        "Use your Firestore tools, generate_destination_image, generate_destination_video, geocode_address, find_nearby_places, get_live_destination_info, calculate_trip_budget, and get_weather tools to assist travelers."
    ),
    workflow_description="Analyze the user request, call tools to gather accurate data, and return structured A2UI UI cards when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        list_destinations,
        get_destination_details,
        add_destination,
        get_weather,
        calculate_trip_budget,
        get_live_destination_info,
        geocode_address,
        find_nearby_places,
        generate_destination_image,
        generate_destination_video,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
