# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import dotenv
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
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

try:
    from .a2ui_utils import a2ui_callback
except ImportError:
    from app.a2ui_utils import a2ui_callback

dotenv.load_dotenv()


MODEL = "gemini-3.6-flash"
PROJECT_ID = "qwiklabs-gcp-03-f6ec19d098cc"
BUCKET_NAME = "floracare-media-qwiklabs-gcp-03-f6ec19d098cc"
IMAGE_MODEL = "gemini-3.1-flash-lite-image"
VIDEO_MODEL = "gemini-omni-flash-preview"
MEMORY_BANK_ID = "5424775966679367680"
LOCATION = "us-east1"

# Lazily initialized Firestore client
_db: Optional[firestore.Client] = None


def get_firestore_client() -> firestore.Client:
    """Returns the Firestore client initialized with the hardcoded project ID."""
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID)
    return _db


def list_inventory(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """List plants available in the greenhouse inventory, optionally filtered by category.

    Args:
        category: Optional category filter (e.g., 'Tropical Foliage', 'Succulent', 'Indoor Tree', 'Flowering Houseplant', 'Trailing Vine').

    Returns:
        A list of plant records with their id, name, species, category, difficulty, light requirements, watering interval, price, and stock.
    """
    db = get_firestore_client()
    collection = db.collection("inventory")
    if category:
        docs = collection.where("category", "==", category).stream()
    else:
        docs = collection.stream()

    items = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        items.append(data)
    return items


def get_plant(plant_id: str) -> Dict[str, Any]:
    """Retrieve detailed care instructions, watering intervals, and stock for a specific plant.

    Args:
        plant_id: The document ID of the plant (e.g. 'monstera_deliciosa', 'snake_plant', 'fiddle_leaf_fig', 'peace_lily', 'pothos_golden').

    Returns:
        The plant information dictionary, or an error dictionary if not found.
    """
    db = get_firestore_client()
    doc_ref = db.collection("inventory").document(plant_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {"error": f"Plant with id '{plant_id}' not found in inventory."}
    data = doc.to_dict()
    data["id"] = doc.id
    return data


def add_plant(
    plant_id: str,
    name: str,
    species: str,
    category: str,
    care_difficulty: str,
    light_requirements: str,
    watering_interval_days: int,
    price: float,
    stock: int,
    description: str,
) -> Dict[str, Any]:
    """Add a new plant to the greenhouse inventory.

    Args:
        plant_id: Unique slug identifier for the plant document (e.g. 'zz_plant').
        name: Common name of the plant (e.g. 'ZZ Plant').
        species: Botanical/scientific name (e.g. 'Zamioculcas zamiifolia').
        category: Category/type of plant (e.g. 'Tropical Foliage', 'Succulent').
        care_difficulty: Difficulty level (e.g. 'Beginner', 'Easy', 'Moderate', 'Advanced').
        light_requirements: Lighting needs (e.g. 'Low to bright indirect light').
        watering_interval_days: Recommended watering frequency in days.
        price: Price in USD.
        stock: Available quantity in stock.
        description: Brief description of the plant and care notes.

    Returns:
        Status message with confirmation of the added plant.
    """
    db = get_firestore_client()
    plant_data = {
        "id": plant_id,
        "name": name,
        "species": species,
        "category": category,
        "care_difficulty": care_difficulty,
        "light_requirements": light_requirements,
        "watering_interval_days": watering_interval_days,
        "price": price,
        "stock": stock,
        "description": description,
    }
    db.collection("inventory").document(plant_id).set(plant_data)
    return {"status": "success", "message": f"Successfully added {name} ({plant_id}) to inventory.", "plant": plant_data}


def update_plant_stock(plant_id: str, new_stock: int) -> Dict[str, Any]:
    """Update the available inventory count for a plant.

    Args:
        plant_id: The document ID of the plant to update.
        new_stock: The updated quantity count in stock.

    Returns:
        Status message indicating success or error.
    """
    db = get_firestore_client()
    doc_ref = db.collection("inventory").document(plant_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {"error": f"Plant with id '{plant_id}' not found in inventory."}
    doc_ref.update({"stock": new_stock})
    return {"status": "success", "message": f"Updated stock for {plant_id} to {new_stock}."}


def calculate_watering_schedule(plant_id: str, last_watered_date: str) -> Dict[str, Any]:
    """Calculate the next watering date and schedule status for a plant based on when it was last watered.

    Args:
        plant_id: The identifier or name of the plant (e.g. 'monstera_deliciosa', 'snake_plant', 'fiddle_leaf_fig', 'peace_lily', 'pothos_golden').
        last_watered_date: The date the plant was last watered, formatted as 'YYYY-MM-DD'.

    Returns:
        A dictionary with last watered date, interval in days, next due date, days until next watering, and status ('UP_TO_DATE', 'DUE_TODAY', or 'OVERDUE').
    """
    plant_info = get_plant(plant_id)
    if "error" in plant_info:
        # Fallback interval if plant not found directly
        interval = 7
        plant_name = plant_id
    else:
        interval = plant_info.get("watering_interval_days", 7)
        plant_name = plant_info.get("name", plant_id)

    try:
        last_date = datetime.date.fromisoformat(last_watered_date)
    except ValueError:
        return {"error": f"Invalid date format '{last_watered_date}'. Please use YYYY-MM-DD."}

    today = datetime.date.today()
    next_due_date = last_date + datetime.timedelta(days=interval)
    days_until_due = (next_due_date - today).days

    if days_until_due < 0:
        status = "OVERDUE"
    elif days_until_due == 0:
        status = "DUE_TODAY"
    else:
        status = "UP_TO_DATE"

    return {
        "plant_name": plant_name,
        "plant_id": plant_id,
        "last_watered_date": last_watered_date,
        "watering_interval_days": interval,
        "next_due_date": next_due_date.isoformat(),
        "days_until_due": days_until_due,
        "status": status,
    }


def search_species_taxonomy(scientific_or_common_name: str) -> Dict[str, Any]:
    """Look up botanical taxonomy and scientific classification for a plant species using the free GBIF public API.

    Args:
        scientific_or_common_name: The botanical or common name of the plant (e.g. 'Monstera deliciosa', 'Sansevieria', 'Ficus lyrata', 'Epipremnum aureum').

    Returns:
        A dictionary containing scientific name, family, genus, kingdom, rank, and taxonomic status.
    """
    import urllib.parse
    import urllib.request
    import json
    import os

    # GBIF API is completely free and requires no key, but check env var if one is ever configured
    _api_key = os.environ.get("GBIF_API_KEY")
    encoded_name = urllib.parse.quote(scientific_or_common_name.strip())
    url = f"https://api.gbif.org/v1/species/match?name={encoded_name}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FloraCare-Agent/1.0"})
        if _api_key:
            req.add_header("Authorization", f"Bearer {_api_key}")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            
        if data.get("matchType") == "NONE":
            return {"error": f"No botanical match found for '{scientific_or_common_name}'."}

        return {
            "query": scientific_or_common_name,
            "scientific_name": data.get("scientificName"),
            "canonical_name": data.get("canonicalName"),
            "rank": data.get("rank"),
            "status": data.get("status"),
            "kingdom": data.get("kingdom"),
            "phylum": data.get("phylum"),
            "class": data.get("class"),
            "order": data.get("order"),
            "family": data.get("family"),
            "genus": data.get("genus"),
            "confidence": data.get("confidence"),
        }
    except Exception as e:
        return {"error": f"Failed to query GBIF API: {str(e)}"}


def geocode_address(address: str) -> Dict[str, Any]:
    """Turn a street address, city, or landmark into geographic coordinates (latitude, longitude) using the Google Maps Geocoding API.

    Args:
        address: The address or place name to geocode (e.g. 'Seattle, WA', '1600 Amphitheatre Pkwy, Mountain View, CA').

    Returns:
        A dictionary with the formatted address, latitude, longitude, and place_id.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key or api_key == "PASTE_KEY_HERE":
        return {"error": "GOOGLE_MAPS_API_KEY is not set or still contains the placeholder. Please configure a valid key in .env."}

    encoded_address = urllib.parse.quote(address.strip())
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FloraCare-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        status = data.get("status")
        if status != "OK" or not data.get("results"):
            return {"error": f"Geocoding failed with status '{status}': {data.get('error_message', 'No results found.')}"}

        result = data["results"][0]
        location = result.get("geometry", {}).get("location", {})
        return {
            "formatted_address": result.get("formatted_address"),
            "latitude": location.get("lat"),
            "longitude": location.get("lng"),
            "place_id": result.get("place_id"),
        }
    except Exception as e:
        return {"error": f"Failed to call Geocoding API: {str(e)}"}


def search_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "florist",
    radius_meters: float = 5000.0,
) -> Dict[str, Any]:
    """Find nearby places (such as florists, garden centers, or plant nurseries) of a given type around coordinates using the Places API (New).

    Args:
        latitude: Latitude of the center point.
        longitude: Longitude of the center point.
        place_type: Place type to search for (e.g. 'florist', 'park', 'store').
        radius_meters: Search radius in meters (default 5000 meters).

    Returns:
        A dictionary containing a list of nearby places with their name, address, and location.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key or api_key == "PASTE_KEY_HERE":
        return {"error": "GOOGLE_MAPS_API_KEY is not set or still contains the placeholder. Please configure a valid key in .env."}

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }
    payload = {
        "includedTypes": [place_type],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": radius_meters,
            }
        },
    }

    try:
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        places_out = []
        for p in data.get("places", []):
            display_name = p.get("displayName", {}).get("text", "Unknown")
            address = p.get("formattedAddress", "Unknown address")
            loc = p.get("location", {})
            places_out.append({
                "name": display_name,
                "address": address,
                "location": loc,
            })

        return {
            "place_type": place_type,
            "count": len(places_out),
            "places": places_out,
        }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return {"error": f"Places API returned HTTP {e.code}: {error_body}"}
    except Exception as e:
        return {"error": f"Failed to call Places API (New): {str(e)}"}


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        city: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


async def generate_plant_image(
    prompt: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Generate an image of a plant, greenhouse arrangement, or botanical item using the gemini-3.1-flash-lite-image model.

    The generated image is saved as a session artifact (viewable in the Playground's Artifacts panel)
    and uploaded to the public Cloud Storage bucket, returning its public HTTPS URL.

    Args:
        prompt: A descriptive prompt for the plant or botanical scene to generate (e.g., 'A healthy mature Fiddle Leaf Fig tree in a ceramic pot by a bright window').

    Returns:
        A dictionary containing the prompt, public storage URL, and status.
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="global",
        )
        response = genai_client.models.generate_content(
            model=IMAGE_MODEL,
            contents=prompt,
        )

        image_part = None
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data and part.inline_data.data:
                    image_part = part
                    break
            if image_part:
                break

        if not image_part:
            return {"error": "No image data was generated by the model."}

        image_bytes = image_part.inline_data.data
        mime_type = image_part.inline_data.mime_type or "image/jpeg"
        ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else "png"

        random_id = uuid.uuid4().hex[:12]
        object_name = f"plants/{random_id}.{ext}"

        # 1. Save artifact if tool_context is available
        if tool_context:
            artifact_filename = f"plant_{random_id[:8]}.{ext}"
            await tool_context.save_artifact(filename=artifact_filename, artifact=image_part)

        # 2. Upload same bytes directly to Cloud Storage bucket without writing to local file
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(object_name)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{object_name}"

        return {
            "status": "success",
            "prompt": prompt,
            "public_url": public_url,
            "mime_type": mime_type,
            "message": f"Image generated and uploaded. Public URL: {public_url}",
        }
    except Exception as e:
        return {"error": f"Failed to generate and upload image: {str(e)}"}


async def generate_plant_video(
    prompt: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Generate a short video of a plant, greenhouse scene, or botanical item using Google's Omni model (gemini-omni-flash-preview) in the global region.

    The generated video is saved as a session artifact (viewable in the Playground's Artifacts panel)
    and uploaded to the public Cloud Storage bucket, returning its public HTTPS URL.

    Args:
        prompt: A descriptive prompt for the plant or greenhouse video to generate (e.g., 'A 5 second time-lapse of a green Monstera leaf uncurling in soft morning sunlight').

    Returns:
        A dictionary containing the prompt, public storage URL, and status.
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="global",
        )
        interaction = genai_client.interactions.create(
            model=VIDEO_MODEL,
            input=prompt,
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(interaction, "output_video") and interaction.output_video:
            ov = interaction.output_video
            raw_data = getattr(ov, "data", None) if not isinstance(ov, dict) else ov.get("data")
            if raw_data:
                if isinstance(raw_data, str):
                    video_bytes = base64.b64decode(raw_data)
                elif isinstance(raw_data, (bytes, bytearray)):
                    video_bytes = bytes(raw_data)
            mime_type = getattr(ov, "mime_type", "video/mp4") if not isinstance(ov, dict) else ov.get("mime_type", "video/mp4")

        # Fallback inspection of steps if output_video attribute isn't directly populated
        if not video_bytes and hasattr(interaction, "steps"):
            for step in getattr(interaction, "steps", []):
                content = getattr(step, "content", []) if not isinstance(step, dict) else step.get("content", [])
                for item in (content or []):
                    item_type = getattr(item, "type", None) if not isinstance(item, dict) else item.get("type")
                    if item_type == "video":
                        raw_data = getattr(item, "data", None) if not isinstance(item, dict) else item.get("data")
                        if raw_data:
                            video_bytes = base64.b64decode(raw_data) if isinstance(raw_data, str) else bytes(raw_data)
                            mime_type = getattr(item, "mime_type", "video/mp4") if not isinstance(item, dict) else item.get("mime_type", "video/mp4")
                            break
                if video_bytes:
                    break

        if not video_bytes:
            return {"error": "No video data was returned by the Omni model."}

        random_id = uuid.uuid4().hex[:12]
        ext = "mp4"
        object_name = f"videos/{random_id}.{ext}"

        # 1. Save artifact if tool_context is available so it shows up in the Playground's Artifacts panel
        if tool_context:
            artifact_filename = f"plant_video_{random_id[:8]}.{ext}"
            video_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename=artifact_filename, artifact=video_part)

        # 2. Upload same bytes directly to Cloud Storage bucket without writing to a local file
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(object_name)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{object_name}"

        return {
            "status": "success",
            "prompt": prompt,
            "public_url": public_url,
            "mime_type": mime_type,
            "message": f"Video generated and uploaded. Public URL: {public_url}",
        }
    except Exception as e:
        return {"error": f"Failed to generate and upload video: {str(e)}"}


def _get_sandbox_code_executor() -> Optional[AgentEngineSandboxCodeExecutor]:
    """Initializes AgentEngineSandboxCodeExecutor using sandbox or Agent Engine from deployment_metadata.json."""
    metadata_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deployment_metadata.json")
    sandbox_id = None
    engine_id = None
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                sandbox_id = meta.get("sandbox_resource_name")
                engine_id = meta.get("remote_agent_runtime_id")
        except Exception:
            pass
    if sandbox_id:
        return AgentEngineSandboxCodeExecutor(sandbox_resource_name=sandbox_id)
    elif engine_id:
        return AgentEngineSandboxCodeExecutor(agent_engine_resource_name=engine_id)
    return None


def memory_bank_service_builder() -> VertexAiMemoryBankService:
    """Builds VertexAiMemoryBankService for deployed runtime and agent engine memory integration."""
    return VertexAiMemoryBankService(
        project=PROJECT_ID,
        location=LOCATION,
        agent_engine_id=MEMORY_BANK_ID,
    )


# WRITE: after each turn, send the session to Memory Bank for extraction.
async def generate_memories_callback(callback_context: CallbackContext) -> None:
    """Extracts durable facts and preferences into the Vertex AI Memory Bank."""
    if getattr(callback_context, "_invocation_context", None) and getattr(callback_context._invocation_context, "memory_service", None):
        try:
            await callback_context.add_session_to_memory()
        except Exception:
            pass
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are FloraCare, an intelligent plant care and greenhouse assistant. "
        "You help plant enthusiasts care for their house plants and discover new varieties. "
        "You remember the user's stated preferences, indoor plant collection, experience level, "
        "and details from previous conversations to personalize your responses across sessions. "
        "CRITICAL FOR MEMORY AND SAFETY: You must always remember all user allergies, sensitivities, "
        "and health reactions (such as pollen allergies, plant sap/contact dermatitis, fragrance sensitivities, "
        "or pet/family allergies). When a user mentions any allergy, acknowledge it and ensure it is remembered. "
        "Always review recalled memories and never recommend or suggest plants that conflict with the user's allergies. "
        "You have access to the greenhouse inventory stored in Firestore, botanical taxonomy from GBIF, "
        "Google Maps tools (geocode_address, search_nearby_places) to locate nearby plant shops, nurseries, and florists, "
        "image generation (generate_plant_image) using gemini-3.1-flash-lite-image to generate visuals of plants, "
        "and video generation (generate_plant_video) using gemini-omni-flash-preview to generate short videos of plants and greenhouse scenes. "
        "You also have a safe Python code execution sandbox powered by Agent Engine to run calculations, "
        "data analysis, or algorithmic tasks when needed. "
        "Use your tools (PreloadMemoryTool, list_inventory, get_plant, add_plant, update_plant_stock, "
        "calculate_watering_schedule, search_species_taxonomy, geocode_address, search_nearby_places, generate_plant_image, generate_plant_video) "
        "and code execution to assist users."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property (\'h1\', \'h2\', \'body\') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or \'kind\'/\'data\'/\'metadata\' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=_get_sandbox_code_executor(),
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        list_inventory,
        get_plant,
        add_plant,
        update_plant_stock,
        calculate_watering_schedule,
        search_species_taxonomy,
        geocode_address,
        search_nearby_places,
        generate_plant_image,
        generate_plant_video,
        get_weather,
        get_current_time,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
