from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi import HTTPException

def obtener_error_legible(exc: Exception) -> tuple[int, str]:
    """
    Transforma cualquier excepción técnica en un mensaje 
    que un humano (y tu Front) puedan entender.
    """
    if isinstance(exc, RequestValidationError):
        errors = exc.errors()
        # Caso específico: Error de formato en el Email
        if any("email" in str(e.get("loc", "")) for e in errors):
            print(422, "El formato del email es inválido para el Sistema.")
            return 422, "ERR_INVALID_EMAIL"
        
        # Caso genérico de validación (Pydantic)
        campo = errors[0].get("loc", ["dato"])[-1]
        print(422, f"Error en el campo {campo}: {errors[0].get('msg')}")
        return 422, "ERR_VALIDATION_FAILED"

    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        return exc.status_code, exc.detail
    
    # 3. NUEVO: Errores que vienen de la BBDD (RPC / RAISE EXCEPTION)
    # Las excepciones de Supabase suelen contener el mensaje en el atributo 'message'
    # o al convertir la excepción a string.
    mensaje_error = str(exc)
    
    # Lista de errores personalizados que definimos en nuestras funciones SQL
    errores_sistema = [
        "ERR_SHOP_INSUFFICIENT_GOLD",
        "ERR_SHOP_ITEM_NOT_FOUND",

        "ERR_STAT_INSUFFICIENT_POINTS",
        "ERR_STAT_MIN_ONE_POINT",
        "ERR_NEGATIVE_STATS",

        "ERR_HUNTER_NOT_FOUND",
        "ERR_SKILL_NOT_FOUND_OR_NOT_OWNED",
        "ERR_SKILL_MAX_LEVEL_REACHED",
        "ERR_SKILL_INSUFFICIENT_POINTS",

        "ERR_ITEM_NOT_FOUND"
    ]
    for error in errores_sistema:
        if error in mensaje_error:
            # Si encontramos nuestra clave, devolvemos un 400 (Bad Request)
            # para que el Front sepa que es un error de lógica de juego
            return 400, error

    # Errores inesperados de código (500)
    print(500, f"Fallo crítico en el Sistema: porfavor intente más tarde. detalle técnico: {str(exc)}")
    return 500, "ERR_INTERNAL_SYSTEM"