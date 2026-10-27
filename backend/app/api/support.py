from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import DB, require_roles
from app.db.models import Usuario
from app.support.service import DiagnosticInput, DiagnosticOutput, diagnose_account

router = APIRouter(tags=["Soporte de cuentas"])
Admin = Annotated[Usuario, Depends(require_roles("administrador_plataforma"))]


@router.post("/admin/diagnostico-cuenta", response_model=DiagnosticOutput)
def account_diagnostic(data: DiagnosticInput, db: DB, user: Admin):
    # POST evita incluir el correo en URLs y registros de acceso. No escribe datos.
    return diagnose_account(db, data.correo)
