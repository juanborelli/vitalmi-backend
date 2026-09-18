import os
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv

# 1. Cargar variables de entorno
# Lee el archivo .env en local; en Railway usa las variables de la plataforma automáticamente
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Error: Faltan las credenciales de Supabase en las variables de entorno.")

# 2. Inicializar cliente
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def ejecutar_ingesta():
    archivo_csv = "Medicos_Piloto_Sur.csv"
    print(f"Leyendo datos de: {archivo_csv}")
    
    try:
        df = pd.read_csv(archivo_csv)
        
        # Asignar explícitamente el valor True a todos los registros de este lote
        df['medicos_piloto_sur'] = True
            
        registros_procesados = 0
        registros_nuevos = 0
        registros_actualizados = 0
        
        for _, fila in df.iterrows():
            fila_limpia = {}
            # Filtrar valores nulos o vacíos para no borrar datos existentes
            for columna, valor in fila.items():
                if pd.notna(valor) and str(valor).strip() != "":
                    fila_limpia[columna] = valor
            
            if 'nombre' not in fila_limpia:
                continue

            nombre_medico = fila_limpia['nombre']
            
            # Buscar si el médico ya existe en la base de datos
            resultado_busqueda = supabase.table("vitalmi_directorio_master").select("id").eq("nombre", nombre_medico).execute()
            
            if len(resultado_busqueda.data) > 0:
                # EL MÉDICO EXISTE: Actualizar usando su ID
                id_existente = resultado_busqueda.data[0]['id']
                supabase.table("vitalmi_directorio_master").update(fila_limpia).eq("id", id_existente).execute()
                registros_actualizados += 1
            else:
                # EL MÉDICO NO EXISTE: Insertar nuevo registro
                supabase.table("vitalmi_directorio_master").insert(fila_limpia).execute()
                registros_nuevos += 1
                
            registros_procesados += 1
            print(f"Procesado: {nombre_medico} ({registros_procesados}/{len(df)})")
            
        print("\n--- RESUMEN DE INGESTA ---")
        print(f"Total procesados: {registros_procesados}")
        print(f"Nuevos insertados: {registros_nuevos}")
        print(f"Perfiles actualizados: {registros_actualizados}")
        
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo '{archivo_csv}'.")
    except Exception as e:
        print(f"Error general: {e}")

if __name__ == "__main__":
    ejecutar_ingesta()