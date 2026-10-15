"""Seed script for FloraCare inventory in Firestore."""
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-f6ec19d098cc"

PLANTS = [
    {
        "id": "monstera_deliciosa",
        "name": "Monstera Deliciosa",
        "species": "Monstera deliciosa",
        "category": "Tropical Foliage",
        "care_difficulty": "Easy",
        "light_requirements": "Medium to bright indirect light",
        "watering_interval_days": 7,
        "price": 28.0,
        "stock": 14,
        "description": "Famous for its natural leaf holes (fenestrations). Thrives in humid, indirect light environments.",
    },
    {
        "id": "snake_plant",
        "name": "Snake Plant",
        "species": "Sansevieria trifasciata",
        "category": "Succulent",
        "care_difficulty": "Beginner",
        "light_requirements": "Low to bright indirect light",
        "watering_interval_days": 14,
        "price": 18.0,
        "stock": 25,
        "description": "Nearly indestructible architectural houseplant that tolerates low light and drought.",
    },
    {
        "id": "fiddle_leaf_fig",
        "name": "Fiddle Leaf Fig",
        "species": "Ficus lyrata",
        "category": "Indoor Tree",
        "care_difficulty": "Moderate",
        "light_requirements": "Bright filtered light",
        "watering_interval_days": 7,
        "price": 45.0,
        "stock": 8,
        "description": "Popular ornamental tree with large violin-shaped leaves that loves stable environments.",
    },
    {
        "id": "peace_lily",
        "name": "Peace Lily",
        "species": "Spathiphyllum wallisii",
        "category": "Flowering Houseplant",
        "care_difficulty": "Easy",
        "light_requirements": "Low to medium indirect light",
        "watering_interval_days": 5,
        "price": 22.0,
        "stock": 12,
        "description": "Lush foliage with elegant white blooms that visually droops to signal when it needs water.",
    },
    {
        "id": "pothos_golden",
        "name": "Golden Pothos",
        "species": "Epipremnum aureum",
        "category": "Trailing Vine",
        "care_difficulty": "Beginner",
        "light_requirements": "Low to bright indirect light",
        "watering_interval_days": 7,
        "price": 15.0,
        "stock": 30,
        "description": "Fast-growing cascading vine with heart-shaped leaves variegated in green and gold.",
    },
]

def seed():
    db = firestore.Client(project=PROJECT_ID)
    collection = db.collection("inventory")
    for plant in PLANTS:
        doc_id = plant["id"]
        doc_ref = collection.document(doc_id)
        doc_ref.set(plant)
        print(f"Seeded: {doc_id} -> {plant['name']}")
    print(f"Successfully seeded {len(PLANTS)} plants into Firestore collection 'inventory'.")

if __name__ == "__main__":
    seed()
