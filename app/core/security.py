# app/core/security.py
from fastapi import HTTPException, Cookie, Depends
from typing import Optional
from app.core.config import supabase_auth

async def validate_hunter_session(hunter_session: Optional[str] = Cookie(None)):
    """
    Dependencia para validar la sesión del cazador mediante la cookie.
    """
    if not hunter_session:
        print(401, "Acceso denegado: No se encontró la cookie de sesión.")
        raise HTTPException(
            status_code=401, 
            detail="ERR_AUTH_REQUIRED"
        )
    
    try:
        # Verificamos el token con Supabase Auth
        user_res = supabase_auth.auth.get_user(hunter_session)
        # Devolvemos directamente el ID del usuario
        return user_res.user.id
    except Exception:
        print(401, "SESIÓN INVÁLIDA: El token ha expirado o es corrupto.")
        raise HTTPException(
            status_code=401, 
            detail="ERR_AUTH_SESSION_EXPIRED"
        )
    
# ─────────────────────────────────────────────
# HELPERS DE AUTENTICACIÓN
# ─────────────────────────────────────────────

def _validate_ws_session(hunter_session: str | None) -> str | None:
    """Valida la cookie y devuelve el user_id, o None si es inválida."""
    if not hunter_session:
        return None
    try:
        user_res = supabase_auth.auth.get_user(hunter_session)
        return user_res.user.id
    except Exception:
        return None