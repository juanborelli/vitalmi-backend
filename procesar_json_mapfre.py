import os
import json
import glob
import pandas as pd

def procesar_archivos_json():
    print("=== 🚀 PROCESANDO ARCHIVOS JSON DE MAPFRE SALUD ARS ===")
    
    ruta_base = os.path.dirname(os.path.abspath(__file__))
    carpeta_json = os.path.join(ruta_base, "json_medicos")
    
    # Si existe la carpeta json_medicos busca allí, si no, busca .json sueltos ignorando site-packages
    if os.path.exists(carpeta_json):
        archivos_json = glob.glob(os.path.join(carpeta_json, "*.json"))
    else:
        archivos_json = [f for f in glob.glob(os.path.join(ruta_base, "*.json")) if "venv" not in f and "node_modules" not in f]
    
    print(f"📍 Carpeta analizada: {carpeta_json if os.path.exists(carpeta_json) else ruta_base}")
    print(f"📂 Archivos JSON encontrados: {len(archivos_json)}")
    
    registros = []

    for ruta in archivos_json:
        nombre_archivo = os.path.basename(ruta)
        print(f"📄 Procesando: {nombre_archivo}...")
        
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                content = json.load(f)

            # Manejar si el JSON es una lista o un solo objeto
            items = content if isinstance(content, list) else [content]

            for item in items:
                nombre = str(item.get("name", "")).strip()
                if not nombre or "playwright" in nombre.lower():
                    continue

                centro = str(item.get("location", "")).strip() or "Consulta Privada"
                direccion = str(item.get("address", "")).strip() or "No especificada"

                # Teléfonos
                phones_list = item.get("phoneNumbers", [])
                telefonos = []
                if isinstance(phones_list, list):
                    for p in phones_list:
                        if isinstance(p, dict):
                            val = p.get("value", "").strip()
                            if val:
                                telefonos.append(val)
                        elif isinstance(p, str):
                            telefonos.append(p.strip())
                tel_str = " / ".join(list(dict.fromkeys(telefonos))) if telefonos else "No disponible"

                # Especialidad
                specs = item.get("specialty", [])
                especialidad = "General"
                if isinstance(specs, list) and len(specs) > 0:
                    especialidad = specs[0].get("name", "General") if isinstance(specs[0], dict) else str(specs[0])

                ciudad = str(item.get("city", "")).strip() or "San Cristóbal"
                sector = str(item.get("sector", "")).strip()

                tipo_obj = item.get("type", {})
                tipo = tipo_obj.get("name", "MEDICO") if isinstance(tipo_obj, dict) else "MEDICO"

                registros.append({
                    "ID": item.get("id", ""),
                    "Nombre": nombre,
                    "Tipo Prestador": tipo,
                    "Especialidad": especialidad,
                    "Centro Médico": centro,
                    "Dirección": direccion,
                    "Teléfono": tel_str,
                    "Ciudad": ciudad,
                    "Sector": sector,
                    "ARS": "Mapfre Salud ARS"
                })

        except Exception as e:
            print(f"⚠️ Error al leer {nombre_archivo}: {e}")

    if registros:
        df = pd.DataFrame(registros).drop_duplicates(subset=["ID", "Nombre"]).reset_index(drop=True)
        excel_salida = "Directorio_Completo_JSON_Mapfre.xlsx"
        df.to_excel(excel_salida, index=False)
        
        print(f"\n🎉 ¡EXTRACCIÓN EXITOSA! {len(df)} médicos procesados correctamente.")
        print(f"📁 Archivo Excel guardado como: '{excel_salida}'")
        print("\n📋 Muestra de los datos extraídos:")
        print(df[["Nombre", "Especialidad", "Centro Médico", "Teléfono", "Ciudad"]].to_string())
    else:
        print("\n⚠️ No se encontraron objetos JSON válidos en la carpeta 'json_medicos'.")

if __name__ == "__main__":
    procesar_archivos_json()