# 🧠 ESTADO ACTIVO DEL PROYECTO: VitalMi / Gema

## 🎯 Visión General
- **Ecosistema:** DomAI (Matriz) > VitalMi (Plataforma Salud) > Gema (Agente IA Médico).
- **Objetivo Actual:** Consolidar a Gema como un asistente autónomo por WhatsApp con búsqueda semántica precisa y capacidades de voz, respaldado por un directorio médico nacional.

## 🛠️ Stack Tecnológico
- **Backend:** Python 3.x, FastAPI, Uvicorn (Entorno: `venv`).
- **Base de Datos Principal:** Supabase (PostgreSQL + pgvector).
- **Base de Datos Secundaria:** Firebase (Transferencia de confianza/frontend futuro).
- **Motor de IA:** OpenAI (`text-embedding-3-small` para vectores, orquestador LLM).
- **Canal:** WhatsApp (vía webhooks en `evolution_service.py`).

## ✅ Hitos Completados (DONE)
- [x] Conexión de webhooks y mensajería bidireccional por WhatsApp.
- [x] Desarrollo e integración de interacción por voz (STT/TTS).
- [x] Limpieza de credenciales en código (implementación de `.env` y `.cursorrules`).
- [x] Optimización de función RPC en Supabase (`buscar_prestadores_gema`) con soporte `ILIKE` y `unaccent` para búsquedas insensibles a mayúsculas/tildes por provincia y ARS.

## 🔄 Estado Actual (DOING)
- Expandiendo masivamente la base de datos `vitalmi_directorio_master`.
- Ingesta de datos estructurados de principales ARS: **SeNaSa, Yunen, Humano, Mapfre**.
- Ejecutando proceso de vectorización (embeddings) para cruzar eficientemente especialidades, ubicaciones y seguros médicos.

## 🚀 Próximos Pasos (TODO)
1. Validar la precisión de Gema con la base de datos ampliada (evitar alucinaciones con el nuevo volumen de datos).
2. Iniciar el desarrollo de la arquitectura transaccional: **Agendamiento de Citas**.
3. Definir flujos de redirección (Handoff) a humanos o sistemas de clínicas.

## 📂 Archivos Críticos
- `app/services/gema_brain.py`: Orquestador principal e instrucciones del LLM.
- `app/services/evolution_service.py`: Manejador de la API de WhatsApp.
- `app/services/poblar_embeddings.py` / `ingesta_senasa.py`: Scripts de vectorización y carga de datos.
- `.cursorrules`: Reglas estrictas de desarrollo para la IA.

## 🗄️ Estructura Clave de Base de Datos
- **Tabla:** `vitalmi_directorio_master`
- **Campos críticos:** `id`, `nombre`, `tipo_prestador`, `especialidades_consolidadas`, `provincia`, `aseguradoras` (array), `embedding` (vector 1536).
- **Función RPC principal:** `buscar_prestadores_gema`