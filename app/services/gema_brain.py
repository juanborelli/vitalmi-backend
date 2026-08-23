-- 1. Si la tabla 'doctores' ya existía, la renombramos a 'doctores_horarios'
ALTER TABLE IF EXISTS public.doctores RENAME TO doctores_horarios;

-- 2. Si no existía, creamos directamente la tabla 'doctores_horarios'
CREATE TABLE IF NOT EXISTS public.doctores_horarios (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  medico_master_id bigint NULL, -- ID del médico en vitalmi_directorio_master
  horario_base jsonb DEFAULT '{
    "lunes": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
    "martes": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
    "miercoles": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
    "jueves": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
    "viernes": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
    "sabado": [{"bloque": "mañana", "inicio": "09:00", "fin": "14:00"}]
  }'::jsonb,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT doctores_horarios_pkey PRIMARY KEY (id)
);

-- 3. Crear la tabla de bloqueos_medicos apuntando a 'doctores_horarios'
CREATE TABLE IF NOT EXISTS public.bloqueos_medicos (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  doctor_horario_id uuid NULL REFERENCES public.doctores_horarios(id) ON DELETE CASCADE,
  tipo_bloqueo character varying(30) NOT NULL, -- 'bloque', 'dia_completo', 'rango_fechas'
  fecha_inicio date NOT NULL,
  fecha_fin date NOT NULL,
  bloque character varying(20) NULL, -- 'mañana', 'tarde', 'todo_el_dia'
  motivo text NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT bloqueos_medicos_pkey PRIMARY KEY (id)
);

-- Índice para acelerar la validación de bloqueos
CREATE INDEX IF NOT EXISTS idx_bloqueos_horario_fechas 
ON public.bloqueos_medicos USING btree (doctor_horario_id, fecha_inicio, fecha_fin);