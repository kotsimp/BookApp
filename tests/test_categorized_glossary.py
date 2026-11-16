import urllib.request
import json

BASE = "http://127.0.0.1:8000/api"

def api_get(endpoint):
    req = urllib.request.Request(f"{BASE}{endpoint}")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_post(endpoint, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{endpoint}", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_delete(endpoint):
    req = urllib.request.Request(f"{BASE}{endpoint}", method="DELETE")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def test_categorized_glossary_api():
    print("=== Testing Categorized Glossary API ===")
    
    # 1. Flat GET /api/glossary
    status, flat = api_get("/glossary")
    assert status == 200
    assert isinstance(flat, dict)
    assert len(flat) >= 1000
    print(f"  GET /glossary (flat): OK ({len(flat)} terms)")

    # 2. Categorized GET /api/glossary?categorized=true
    status, cat_data = api_get("/glossary?categorized=true")
    assert status == 200
    assert "categories" in cat_data
    assert "counts" in cat_data
    assert "terms" in cat_data
    assert cat_data["counts"]["technical"] >= 500
    assert cat_data["counts"]["literary"] >= 500
    assert cat_data["counts"]["general"] >= 10
    print(f"  GET /glossary?categorized=true: OK (Tech={cat_data['counts']['technical']}, Lit={cat_data['counts']['literary']}, Gen={cat_data['counts']['general']})")

    # 3. Filter by category
    status, tech_only = api_get("/glossary?category=technical")
    assert status == 200
    assert "artificial intelligence" in tech_only
    assert "narrative arc" not in tech_only
    print("  GET /glossary?category=technical: OK (isolated to technical terms)")

    status, lit_only = api_get("/glossary?category=literary")
    assert status == 200
    assert "narrative arc" in lit_only
    assert "artificial intelligence" not in lit_only
    print("  GET /glossary?category=literary: OK (isolated to literary terms)")

    # 4. Add term to specific category
    status, res = api_post("/glossary", {
        "source": "cybernetic organism",
        "target": "κυβερνοργανισμός",
        "category": "technical"
    })
    assert status == 200
    status, tech_check = api_get("/glossary?category=technical")
    assert "cybernetic organism" in tech_check
    print("  POST /glossary (add technical): OK")

    status, res = api_post("/glossary", {
        "source": "tragic flaw",
        "target": "τραγικό ελάττωμα (αμαρτία)",
        "category": "literary"
    })
    assert status == 200
    status, lit_check = api_get("/glossary?category=literary")
    assert "tragic flaw" in lit_check
    print("  POST /glossary (add literary): OK")

    # 5. Clean up added terms
    api_delete("/glossary/cybernetic%20organism")
    api_delete("/glossary/tragic%20flaw")
    print("  DELETE /glossary: OK")

    print("ALL CATEGORIZED GLOSSARY TESTS PASSED!")

if __name__ == "__main__":
    test_categorized_glossary_api()
