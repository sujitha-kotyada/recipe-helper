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

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("recipe-helper-mcp")

@mcp.tool()
def get_fridge_inventory() -> list[str]:
    """Get the current list of ingredients available in the user's fridge and pantry.
    
    Returns:
        A list of ingredient names.
    """
    return [
        "chicken breast", 
        "cherry tomatoes", 
        "penne pasta", 
        "garlic", 
        "olive oil", 
        "spinach", 
        "parmesan cheese",
        "lemon"
    ]

@mcp.tool()
def search_recipe_database(query: str) -> str:
    """Search a recipe database for ideas matching a query string.
    
    Args:
        query: Search keywords (e.g. 'chicken', 'pasta').
        
    Returns:
        Matching recipe summaries and instructions.
    """
    recipes = {
        "chicken": "Garlic Tomato Chicken Pasta: Chicken breast cooked with garlic, cherry tomatoes, and spinach, tossed with penne pasta and parmesan.",
        "pasta": "Tomato Garlic Penne: Penne pasta tossed with sautéed cherry tomatoes, fresh garlic, olive oil, and spinach.",
        "salad": "Spinach Tomato Salad: Fresh spinach salad with cherry tomatoes, shaved parmesan, and olive oil dressing."
    }
    query_lower = query.lower()
    matches = [val for key, val in recipes.items() if key in query_lower]
    if matches:
        return "\n".join(matches)
    return "No direct database match. Feel free to draft a creative recipe with the available ingredients."

@mcp.tool()
def check_allergy_restrictions(ingredient: str, allergy: str) -> str:
    """Check if an ingredient is safe for a given allergy or dietary restriction.
    
    Args:
        ingredient: The ingredient name to check.
        allergy: The allergy or restriction (e.g., 'nuts', 'dairy', 'gluten').
        
    Returns:
        A safety check message with warnings if not safe.
    """
    allergies_db = {
        "nuts": ["peanut", "almond", "walnut", "cashew", "pecan", "hazelnut", "nut"],
        "dairy": ["milk", "cheese", "butter", "cream", "yogurt", "parmesan"],
        "gluten": ["pasta", "wheat", "flour", "barley", "rye", "penne"]
    }
    ing_lower = ingredient.lower()
    all_lower = allergy.lower()
    if all_lower in allergies_db:
        for item in allergies_db[all_lower]:
            if item in ing_lower:
                return f"WARNING: Ingredient '{ingredient}' is NOT safe for a '{allergy}' restriction."
    return f"Ingredient '{ingredient}' is likely safe for a '{allergy}' restriction."

if __name__ == "__main__":
    mcp.run()
