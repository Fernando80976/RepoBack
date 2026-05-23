from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.errors import obtener_error_legible

from app.routers import auth_router, hunter_router, missions_router, skills_router, shop_router, inventory_router, battle_router, ranking_router, dungeons_router, dle_router

app = FastAPI(title="Solo Leveling API - System")

#Comando para crear el entorno virtual:
# python -m venv venv

# Comando para activar venv: 
# .\venv\Scripts\activate

# Comando para ejecutar: 
# uvicorn main:app --reload

# Comando para sacar el requirements.txt:
# pip freeze > requirements.txt

# Comando para instalar las dependencias:
# pip install -r requirements.txt

# Comando para sacar la estructura del proyecto:
# tree app /F /A > estructura.txt

# --- CONFIGURACIÓN DE CORS ---
ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MANEJO GLOBAL DE EXCEPCIONES ---
async def sistema_unified_handler(request: Request, exc: Exception):
    # Usamos la utilidad de la carpeta utils
    status_code, mensaje = obtener_error_legible(exc)

    # 1. Detectar el origen de la petición (viene en los headers del navegador)
    origin = request.headers.get("origin")
    
    # 2. Validar: si el origen está en nuestra lista permitida, lo usamos. 
    # Si no, usamos el primero de la lista (o None para que el navegador bloquee)
    if origin not in ORIGINS:
        origin = None

    print(f"⚠️ [{status_code}] | {mensaje} | Path: {request.url.path}")

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error" if status_code >= 400 else "success",
            "mensaje": mensaje,
            "endpoint": request.url.path
        },
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }
    )

app.add_exception_handler(Exception, sistema_unified_handler)
app.add_exception_handler(StarletteHTTPException, sistema_unified_handler)
app.add_exception_handler(RequestValidationError, sistema_unified_handler)

# --- REGISTRO DE RUTAS ---
app.include_router(auth_router)
app.include_router(hunter_router)
app.include_router(missions_router)
app.include_router(skills_router)
app.include_router(shop_router)
app.include_router(inventory_router)
app.include_router(battle_router)
app.include_router(ranking_router)
app.include_router(dungeons_router)
app.include_router(dle_router)

@app.get("/")
async def root():
    return {"message": "SISTEMA OPERATIVO SOLO LEVELING ACTIVO"}