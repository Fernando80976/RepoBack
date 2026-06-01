
from app.utils.errors import obtener_error_legible
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException

class DummyValidationError(RequestValidationError):
    def __init__(self):
        # El primer argumento es errors, el segundo es body
        super().__init__([
            {"loc": ("body", "email"), "msg": "invalid email"}
        ])

class DummyHTTPException(HTTPException):
    def __init__(self, status_code, detail):
        super().__init__(status_code=status_code, detail=detail)


def test_obtener_error_legible_email():
    exc = DummyValidationError()
    code, msg = obtener_error_legible(exc)
    assert code == 422
    assert msg == "ERR_INVALID_EMAIL"

def test_obtener_error_legible_http():
    exc = DummyHTTPException(404, "not found")
    code, msg = obtener_error_legible(exc)
    assert code == 404
    assert msg == "not found"

def test_obtener_error_legible_custom():
    class Custom(Exception):
        def __str__(self):
            return "ERR_SHOP_ITEM_NOT_FOUND"
    exc = Custom()
    code, msg = obtener_error_legible(exc)
    assert code == 400
    assert msg == "ERR_SHOP_ITEM_NOT_FOUND"

def test_obtener_error_legible_internal():
    class Custom(Exception):
        def __str__(self):
            return "unexpected error"
    exc = Custom()
    code, msg = obtener_error_legible(exc)
    assert code == 500
    assert msg == "ERR_INTERNAL_SYSTEM"
