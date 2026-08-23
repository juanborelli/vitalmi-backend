import os
import glob
import re
import pandas as pd
from bs4 import BeautifulSoup

def procesar_archivos_m1_m10():
    print("=== 🚀 INICIANDO EXTRACCIÓN DE MODALES (m1.html - m10.html) ===")
    
    ruta_base = os.path.dirname(os.path.abspath(__file__))
    carpeta_objetivo = os.path.join(ruta_base, "medicos_mapfre")
    
    # 1. Buscar m*.html dentro de /medicos_mapfre o en la raíz
    archivos = sorted(glob.glob(os.path.join(carpeta_objetivo, "m*.html")))
    if not archivos:
        archivos = sorted(glob.glob(os.path.join(ruta_base, "m*.html")))

    print(f"📍 Carpeta analizada: {carpeta_objetivo}")
    print(f"📂 Archivos m*.html encontrados: {len(archivos)}")

    if not archivos:
        print("❌ No se encontraron archivos 'm1.html', 'm2.html', etc.")
        return

    medicos_extraidos = []

    for ruta in archivos:
        nombre_archivo = os.path.basename(ruta)
        print(f"\n📖 Leyendo: {nombre_archivo}...")

        try:
            with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            soup = BeautifulSoup(content, "html.parser")
            texto_limpio = soup.get_text(separator="\n", strip=True)
            lineas = [l.strip() for l in texto_limpio.split("\n") if l.strip()]

            # Extraer Nombre (título del modal o primera línea válida)
            titulo = soup.find(["h1", "h2", "h3", "h4", "h5"])
            nombre = titulo.get_text(strip=True) if titulo else "Sin Nombre"
            
            # Limpiar ruidos comunes del nombre
            if "sesión" in nombre.lower() or "mapfre" in nombre.lower():
                nombre = next((l for l in lineas if "dr" in l.lower() or "dra" in l.lower() or len(l) > 10), "Médico Desconocido")

            # Extraer Especialidad
            esp_tag = soup.find(class_=lambda c: c and "specialty" in c.lower())
            especialidad = esp_tag.get_text(strip=True).replace("-", "").strip() if esp_tag else "General"

            # Extraer Teléfonos con expresión regular
            telefonos = re.findall(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', texto_limpio)
            tel_str = " / ".join(list(dict.fromkeys(telefonos))) if telefonos else "No disponible"

            # Extraer Dirección y Centro Médico
            centro = "Consulta Privada"
            direccion = "San Cristóbal"

            for idx, l in enumerate(lineas):
                if "dirección" in l.lower() and idx + 1 < len(lineas):
                    siguiente = lineas[idx + 1]
                    if any(c in siguiente.lower() for c in ["clinica", "centro", "hospital", "plaza", "consultorio", "grupo", "servicios"]):
                        centro = siguiente
                        direccion = lineas[idx + 2] if idx + 2 < len(lineas) else "San Cristóbal"
                    else:
                        direccion = siguiente

            medicos_extraidos.append({
                "Archivo": nombre_archivo,
                "Nombre": nombre,
                "Especialidad": especialidad,
                "Centro Médico": centro,
                "Dirección": direccion,
                "Teléfono": tel_str,
                "ARS": "Mapfre Salud ARS",
                "Provincia": "San Cristóbal"
            })

            print(f"   ✅ Nombre:    {nombre}")
            print(f"   ✅ Especial:  {especialidad}")
            print(f"   ✅ Teléfono:  {tel_str}")

        except Exception as e:
            print(f"   ⚠️ Error al procesar {nombre_archivo}: {e}")

    if medicos_extraidos:
        df = pd.DataFrame(medicos_extraidos)
        salida_excel = "Tabla_10_Medicos_Mapfre.xlsx"
        df.to_excel(salida_excel, index=False)
        print(f"\n🎉 ¡PROCESADO CON ÉXITO! {len(df)} médicos consolidados en '{salida_excel}'.")
    else:
        print("\n❌ No se extrajeron registros.")

if __name__ == "__main__":
    procesar_archivos_m1_m10()