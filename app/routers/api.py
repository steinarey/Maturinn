"""JSON API for recipes. Same service layer as the HTML forms."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Recipe
from app.services import recipes as recipe_svc
from app.services import search as search_svc

router = APIRouter(prefix="/api")


@router.get("/recipes")
def list_recipes(q: str = "", has: list[str] = Query(default=[]),
                 without: list[str] = Query(default=[]), session: Session = Depends(get_session)):
    result = search_svc.search(session, q, has, without)
    return {
        "recipes": [{"id": r.id, "title": r.title, "original_lang": r.original_lang} for r in result.recipes],
        "unknown_ingredients": result.unknown,
    }


@router.get("/recipes/{recipe_id}", response_model=recipe_svc.RecipeOut)
def get_recipe(recipe_id: int, session: Session = Depends(get_session)):
    recipe = recipe_svc.load(session, recipe_id)
    if not recipe:
        raise HTTPException(404)
    return recipe_svc.to_output(recipe)


@router.post("/recipes", response_model=recipe_svc.RecipeOut, status_code=201)
def create_recipe(data: recipe_svc.RecipeIn, session: Session = Depends(get_session)):
    recipe = recipe_svc.save(session, data)
    session.commit()
    return recipe_svc.to_output(recipe_svc.load(session, recipe.id))


@router.put("/recipes/{recipe_id}", response_model=recipe_svc.RecipeOut)
def update_recipe(recipe_id: int, data: recipe_svc.RecipeIn, session: Session = Depends(get_session)):
    recipe = recipe_svc.load(session, recipe_id)
    if not recipe:
        raise HTTPException(404)
    recipe_svc.save(session, data, recipe)
    session.commit()
    return recipe_svc.to_output(recipe_svc.load(session, recipe.id))


@router.delete("/recipes/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, session: Session = Depends(get_session)):
    recipe = session.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(404)
    session.delete(recipe)
    session.commit()
