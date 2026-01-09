
# Precios Cercanos

Aplicación web hecha con **Streamlit** que permite:
- Iniciar sesión por **OTP** (email) usando **Supabase Auth**.
- **Registrar precios** de productos en locales cercanos.
- **Listar precios cercanos** (con etiqueta de confianza según cantidad de reportes).
- Crear **alertas** de precio y recibir **notificaciones** automáticas cuando haya avistamientos **validados** dentro del radio configurado.

## 🗂 Estructura del proyecto

tu_proyecto/
├─ app.py
├─ styles.css
├─ requirements.txt
├─ utils/
│  └─ supabase_client.py
└─ supabase_sql/
├─ nearby_stores.sql
└─ on_sighting_insert.sql

- `app.py`: UI principal en Streamlit (Login, Cargar Precio, Lista de Precios, Alertas).
- `styles.css`: estilos de la interfaz (botones, inputs, tarjetas y badges de confianza).
- `requirements.txt`: dependencias del proyecto.
- `utils/supabase_client.py`: cliente Supabase (lee credenciales de **Streamlit secrets** o **variables de entorno**).
- `supabase_sql/*.sql`: funciones SQL para Supabase (RPC y trigger).

---

## 🚀 Requisitos

- Python 3.10+
- Cuenta y proyecto en **Supabase** con:
  - Tablas: `stores`, `products`, `sightings`, `alerts`, `notifications`, `profiles`
  - Extensión **PostGIS** activada (el proyecto de Supabase ya la trae por defecto en la mayoría de planes).
  - RLS configurado (ver “Modelo de datos y RLS”).

---

## 📦 Instalación (local)

1. **Crear entorno virtual (opcional)**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate     # Windows: .venv\Scripts\activate
         
2. **Instalar dependencias:
    pip install -r requirements.txtShow more lines


3. *Configurar credenciales:

	**Opción A — Streamlit Secrets (Cloud o local)
	En Streamlit Cloud: Settings → Secrets
	SUPABASE_URL = "https://<tu_ref>.supabase.co"
	SUPABASE_ANON_KEY = "eyJhbGciOi..."

	En local, podés usar ~/.streamlit/secrets.toml:
	TOML[general]SUPABASE_URL = "https://<tu_ref>.supabase.co"SUPABASE_ANON_KEY = "eyJhbGciOi..."Show more lines

	**Opción B — Variables de entorno (local)
	export SUPABASE_URL="https://<tu_ref>.supabase.co"export SUPABASE_ANON_KEY="eyJhbGciOi..."Show more lines




4. **Ejecutar la app:
	streamlit run app.pyShow more lines
	Abrí el navegador en la URL que te muestre (habitualmente http://localhost:8501).



🧰 Configuración en Supabase (SQL)

Abrí Supabase Dashboard → SQL Editor y pega cada bloque por separado.

1) RPC nearby_stores
Calcula locales cercanos usando la posición del usuario y el radio. Convierte geom a geography en la consulta para medir correctamente en metros.


CREATE OR REPLACE FUNCTION public.nearby_stores(lat numeric, lon numeric, radius_km numeric)
RETURNS TABLE(id bigint, name text, address text, lat numeric, lon numeric, meters numeric)
LANGUAGE sql
AS $function$
WITH params AS (
  SELECT
    ST_SetSRID(ST_MakePoint(lon::double precision, lat::double precision), 4326)::geography AS user_point,
    (radius_km * 1000)::double precision AS radius_m
)
SELECT
  s.id, s.name, s.address, s.lat, s.lon,
  ST_Distance(s.geom::geography, (SELECT user_point FROM params)) AS meters
FROM public.stores s
WHERE ST_Distance(s.geom::geography, (SELECT user_point FROM params)) <= (SELECT radius_m FROM params)
ORDER BY meters ASC;
$function$;




2) Trigger de validación y notificaciones
Valida un avistamiento si hay ≥3 coincidencias ±1% en 14 días y genera notificaciones para alertas activas dentro del radio.


CREATE OR REPLACE FUNCTION public.on_sighting_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
  total_matches int;
  validated boolean;
BEGIN
  SELECT count(*) INTO total_matches
  FROM public.sightings s
  WHERE s.product_id = NEW.product_id
    AND s.store_id   = NEW.store_id
    AND s.created_at >= now() - interval '14 days'
    AND abs((s.price - NEW.price) / NULLIF(NEW.price, 0)) <= 0.01;

  validated := (total_matches >= 3);

  IF validated THEN
    UPDATE public.sightings SET is_validated = true WHERE id = NEW.id;

    INSERT INTO public.notifications (user_id, alert_id, sighting_id)
    SELECT a.user_id, a.id, NEW.id
    FROM public.alerts a
    JOIN public.stores st ON st.id = NEW.store_id
    WHERE a.active = true
      AND a.product_id = NEW.product_id
      AND (a.target_price IS NULL OR NEW.price <= a.target_price)
      AND ST_Distance(
            st.geom::geography,
            ST_SetSRID(ST_MakePoint(NEW.lon::double precision, NEW.lat::double precision), 4326)::geography
          ) <= a.radius_km * 1000;
  END IF;

  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS trg_on_sighting_insert ON public.sightings;
CREATE TRIGGER trg_on_sighting_insert
AFTER INSERT ON public.sightings
FOR EACH ROW EXECUTE FUNCTION public.on_sighting_insert();



🧱 Modelo de datos y RLS (resumen)
Tablas clave:

stores: locales (id, name, address, lat, lon, geom generado como geometry(Point,4326)), índice GIST en geom.
products: productos (id, name, currency, created_at), UNIQUE(name, currency).
sightings: avistamientos (id, user_id(uuid), product_id, store_id, price, lat, lon, geom generado, created_at, is_validated).
alerts: alertas (id, user_id(uuid), product_id, target_price, radius_km, active, created_at).
notifications: notificaciones (id, user_id, alert_id, sighting_id, created_at, sent).

RLS (Row Level Security) sugeridas:

sightings:

SELECT permitido para usuarios autenticados (visible para todos).
INSERT/UPDATE limitado al dueño: auth.uid() = user_id.


alerts:

SELECT/INSERT limitado al dueño: auth.uid() = user_id.


notifications:

SELECT limitado al dueño: auth.uid() = user_id.




Estas políticas ya están activas en tu proyecto según el snapshot. Si necesitás el SQL exacto para recrearlas, pedímelo y lo agrego acá.


🎛 Variables y estilos

styles.css se carga automáticamente en app.py.
Badges de confianza:

Rojo: 1 reporte
Amarillo: 2–3 reportes
Verde: ≥4 reportes




🔐 Autenticación (OTP por email)

En Login, ingresá tu email → Enviar código → pegá el OTP recibido → Validar código.
El user_id se usa para asociar avistamientos (sightings) y alertas (alerts) del usuario autenticado.
Si la sesión expira, el sistema te pedirá log in nuevamente.


✅ Flujo funcional

Login → obtenés sesión.
Cargar Precio → ingresá lat/lon → elegí local cercano (o creá uno) → cargá producto + precio.
Lista de Precios → ingresá lat/lon → se muestran precios por producto/local con badge de confianza.
Alertas → creá alerta por producto con radio/target → cuando haya avistamientos validados dentro de tu radio y precio, verás notificaciones.


🧪 Pruebas y datos

Para probar la validación automática de sightings, cargá 3 o más avistamientos similares (±1% de precio) en el mismo producto/local dentro de 14 días.
Para recibir una notificación, creá una alerta activa para ese producto con un radio que incluya el local y (opcionalmente) un target_price mayor o igual al precio cargado.


🛠 Troubleshooting

No se encontraron credenciales de Supabase
Verificá que definiste SUPABASE_URL y SUPABASE_ANON_KEY en secrets o variables de entorno.
OTP no llega
Revisá la bandeja de spam/promociones; reintentá y esperá algunos segundos (evitar rate limit).
nearby_stores no devuelve resultados
Comprobá:

Que stores tenga datos con lat/lon.
Que el radio sea suficiente (p. ej. 5–15 km).
Que geom se esté generando (columna calculada a partir de lat/lon).


INSERT en sightings/alerts falla por RLS
Asegurate de estar autenticado y que el user_id sea el del auth.uid().


🗺 Roadmap (sugerido)

Geolocalización del navegador (botón “Usar mi ubicación”) con streamlit.components.v1.
Paginación y filtros en “Lista de Precios” (por producto/tienda, ordenar por precio/fecha).
Edición de avistamientos propios (dentro de una ventana de tiempo).
Exportar resultados (CSV/Excel).


📄 Licencia
Definí la licencia que prefieras (por ejemplo, MIT). Si querés, te preparo el LICENSE.

🙌 Contribución
PRs y sugerencias bienvenidos. Para cambios mayores, abrí un issue y discutimos el enfoque.

Contacto
Si necesitás ayuda para desplegar en Streamlit Cloud o ajustar el esquema de Supabase (índices, RLS, funciones), escribime y lo dejamos fino.
