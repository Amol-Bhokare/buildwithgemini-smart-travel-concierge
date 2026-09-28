"""Seed script for populating initial travel destinations into Firestore."""

from google.cloud import firestore

# HARDCODED PROJECT ID (Required: Agent Platform returns project number for GOOGLE_CLOUD_PROJECT)
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-4ae329ac7f7f"

SEED_DESTINATIONS = [
    {
        "id": "kyoto",
        "name": "Kyoto Ancient Temples & Bamboo Grove",
        "country": "Japan",
        "category": "Cultural",
        "description": "Historic shrines, traditional tea ceremonies, Arashiyama bamboo forest, and Zen gardens.",
        "rating": 4.9,
        "best_season": "Spring (Cherry Blossom) / Autumn",
        "estimated_cost_per_day_usd": 180,
    },
    {
        "id": "santorini",
        "name": "Santorini Cliffside Coastline",
        "country": "Greece",
        "category": "Beach & Island",
        "description": "Iconic white-washed buildings, Aegean Sea sunsets, volcanic beaches, and Mediterranean cuisine.",
        "rating": 4.8,
        "best_season": "Late Spring to Early Autumn",
        "estimated_cost_per_day_usd": 250,
    },
    {
        "id": "banff",
        "name": "Banff National Park & Lake Louise",
        "country": "Canada",
        "category": "Nature & Adventure",
        "description": "Turquoise glacial lakes, majestic Rocky Mountain peaks, alpine hiking trails, and wildlife watching.",
        "rating": 4.9,
        "best_season": "Summer for hiking / Winter for skiing",
        "estimated_cost_per_day_usd": 210,
    },
    {
        "id": "florence",
        "name": "Florence Renaissance Art & Culinary Walk",
        "country": "Italy",
        "category": "Art & Culinary",
        "description": "World-class Renaissance art galleries, Tuscan wine tasting, historic piazzas, and artisanal gelato.",
        "rating": 4.7,
        "best_season": "Spring / Autumn",
        "estimated_cost_per_day_usd": 195,
    },
]


def seed_firestore():
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    collection_ref = db.collection("destinations")

    for dest in SEED_DESTINATIONS:
        doc_id = dest["id"]
        collection_ref.document(doc_id).set(dest)
        print(f"Seeded destination: {dest['name']} ({doc_id})")

    print("\n✅ Firestore seeding completed successfully!")


if __name__ == "__main__":
    seed_firestore()
