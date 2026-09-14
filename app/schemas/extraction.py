from pydantic import BaseModel, Field
from typing import Optional

class ExtraccionIntencion(BaseModel):
    intencion_usuario: str = Field(
        description="La intención principal del usuario: 'buscar' (quiere opciones), 'agendar' (quiere una cita), o 'informacion' (preguntas generales)."
    )
    especialidad: Optional[str] = Field(
        default=None, 
        description="Especialidad médica buscada, ej: 'Cardiología', 'Pediatra'. Debe ser nulo si no se menciona."
    )
    ubicacion_provincia: Optional[str] = Field(
        default=None, 
        description="Provincia o ciudad mencionada, ej: 'San Cristóbal', 'Distrito Nacional'. Nulo si no se menciona."
    )
    aseguradora: Optional[str] = Field(
        default=None, 
        description="ARS o seguro médico mencionado, ej: 'SeNaSa', 'Humano', 'Mapfre'. Nulo si no se menciona."
    )
    tipo_entidad: Optional[str] = Field(
        default=None, 
        description="Tipo de prestador buscado: 'medico', 'centro', 'farmacia', 'laboratorio'."
    )
    nombre_medico: Optional[str] = Field(
        default=None, 
        description="Nombre específico del médico, farmacia o centro si el usuario lo menciona explícitamente."
    )