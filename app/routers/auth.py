from fastapi import APIRouter, HTTPException, Response, Depends
from app.core.config import supabase_auth, supabase_db
from app.models import LoginSchema, SignupSchema
from app.core.security import validate_hunter_session

router = APIRouter(prefix="/auth", tags=["Autenticación"])

@router.get("/verify")
async def verify_session(user_id: str = Depends(validate_hunter_session)):
    """
    Si el flujo llega hasta aquí, significa que el Depends 
    ya validó la sesión con éxito. Solo tenemos que confirmar.
    """
    return {"authenticated": True}

@router.post("/signup")
async def signup(datos: SignupSchema, response: Response):

    try:
        auth_response = supabase_auth.auth.sign_up({
            "email": datos.email,
            "password": datos.password,
            "options": {
                "data": {
                    "display_name": datos.username
                }
            }
        })

    except Exception as e:
        error_msg = str(e).lower()


        # 1. Error de duplicado
        if "already registered" in error_msg or "already exists" in error_msg:
            print(400, "Error al registrar: El email ya está registrado en el Sistema.")
            raise HTTPException(status_code=400, detail="ERR_AUTH_EMAIL_EXISTS")
            
       # 2. Otros errores de Auth (ej. contraseña muy corta si Supabase lo valida)
        print(f"🔥 [SIGNUP ERROR]: {error_msg}")
        raise HTTPException(status_code=400, detail="ERR_AUTH_SIGNUP_FAILED")
    
    # 3. Validación manual (Si Supabase no devuelve error pero tampoco usuario)
    if not auth_response.user:
        print(400, "Error al registrar: No se pudo crear el usuario en el Sistema.")
        raise HTTPException(status_code=400, detail="ERR_AUTH_USER_CREATION_FAILED")

    if auth_response.session:
        token = auth_response.session.access_token
        response.set_cookie(
            key="hunter_session", value=token,
            httponly=True, max_age=3600 * 24, samesite="none", secure=True, path="/"
        )
        return {"status": "success", "message": "MSG_SIGNUP_SUCCESS", "user": auth_response.user}
    
@router.post("/login")
async def login(datos: LoginSchema, response: Response):
    # Por defecto, asumimos que el usuario escribió su email
    email_para_auth = datos.identifier

    # Simplificación: Si el texto NO contiene un '@', es un nombre de usuario
    if "@" not in datos.identifier:
        # Paso 1: Buscamos solo el ID en la tabla profiles (que ya vincula UUID con username)
        res = supabase_db.table("profiles").select("id").eq("username", datos.identifier).execute()

        if not res.data:
            print(404, "el sistema no reconoce a este cazador.")
            raise HTTPException(status_code=404, detail="ERR_AUTH_HUNTER_NOT_FOUND")

        user_id = res.data[0]["id"]

        # Paso 2: Usamos el ID para obtener el email real de la base de datos de Auth
        # Esto es lo más rápido porque vas directo al usuario por su clave primaria (UUID)
        user = supabase_db.auth.admin.get_user_by_id(user_id)
        email_para_auth = user.user.email

    # Capturamos el intento de login para personalizar el mensaje de "Contraseña mal"
    try:
        auth_response = supabase_auth.auth.sign_in_with_password({
            "email": email_para_auth, "password": datos.password
        })
    except Exception:
        # Si falla la contraseña o cualquier cosa en el proceso de auth
        print(401, "Credenciales incorrectas.")
        raise HTTPException(status_code=401, detail="ERR_AUTH_INVALID_CREDENTIALS")

    # Si por alguna razón no hay sesión pero no lanzó excepción
    if not auth_response.session or not auth_response:
        print(401, "Error al iniciar sesión.")
        raise HTTPException(status_code=401, detail="ERR_AUTH_LOGIN_ERROR")

    token = auth_response.session.access_token
    response.set_cookie(
        key="hunter_session", value=token,
        httponly=True, max_age=3600 * 24, samesite="none", secure=True, path="/"
    )
    return {"status": "success", "mensaje": "MSG_LOGIN_SUCCESS", "user": auth_response.user}

@router.post("/logout")
async def logout(response: Response):

    # Intentamos cerrar sesión en Supabase
    try: 
        supabase_auth.auth.sign_out()
    except: pass
        
    # Borramos la cookie del navegador
    response.delete_cookie(key="hunter_session", path="/", samesite="lax", httponly=True)
    return {"message": "MSG_AUTH_LOGOUT_SUCCESS"}