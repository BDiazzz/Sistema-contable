# Sistema de Información Contable (SIC)

Este repositorio contiene una aplicación web completa y monolítica diseñada para la automatización del ciclo contable de una entidad comercial o de servicios. Desarrollado con **Python** y **Django**, el sistema implementa la lógica financiera requerida para el registro de transacciones diarias, la centralización de cuentas en el libro mayor y la generación automatizada de estados financieros bajo principios contables estándar.

La aplicación aprovecha las características nativas de Django (MVT) para el procesamiento seguro de transacciones a través de formularios validados y filtros personalizados de presentación matemática.

---

## 🚀 Características Principales

### 📈 Automatización del Ciclo Contable completo
* **Catálogo de Cuentas:** Estructura organizada jerárquicamente para administrar los activos, pasivos, patrimonio, ingresos y costos (`catalogo.html`).
* **Libro Diario y Registro:** Módulo asíncrono e interactivo para procesar partidas y transacciones contables en tiempo real, validando la partida doble (Debe/Haber).
* **Libro Mayor:** Centralización y agrupación automatizada de los movimientos individuales de las cuentas contables (`libroMayor.html`).

### 📊 Generación de Reportes y Estados Financieros
* **Hoja de Trabajo y Balances:** Estructuración dinámica de la Hoja de Trabajo contable, incluyendo el Balance de Comprobación y el Balance de Comprobación Ajustado.
* **Estados Financieros Clásicos:** Generación automatizada basada en la persistencia de datos de:
  * Estado de Resultados (Pérdidas y Ganancias).
  * Estado de Evolución del Patrimonio (Estado de Capital).
  * Balance General de Cierre.

### 🛡️ Robustez Técnica e Infraestructura
* **Validación mediante Django Forms:** Procesamiento seguro de datos financieros en el servidor utilizando `forms.py` para prevenir datos corruptos o descuadres contables.
* **Filtros Personalizados (Template Tags):** Implementación de lógica matemática e inversión de saldos contables directamente en las vistas a través de etiquetas personalizadas (`math_extras.py`).
* **Pruebas Unitarias Contables:** Cobertura de código específica para verificar la consistencia matemática y cuadre estructural de los estados financieros (`test_balance_general.py`).

---

## 🛠️ Stack Tecnológico

* **Core Backend & Web:** Python 3 + Django Web Framework.
* **Arquitectura:** Patrón Modelo-Vista-Template (MVT).
* **Estilos & UI:** CSS3 modularizado por estado financiero (`estadoResultado.css`, `libroMayor.css`, etc.) y JavaScript vanilla para validaciones dinámicas del lado del cliente.
* **Base de Datos:** PostgreSQL / SQLite (Persistencia indexada relacional para transacciones contables).

---

## 📂 Estructura del Repositorio

El proyecto mantiene la estructura limpia y estandarizada de un entorno Django:

```text
bdiazzz-sistema-contable/
├── manage.py                        # Orquestador de comandos de Django
├── requirements.txt                 # Dependencias del proyecto (Django, etc.)
├── LICENSE                          # Licencia del software
│
├── sic_webproject/                  # Directorio de Configuración Core del Proyecto
│   ├── settings.py                  # Configuraciones globales y base de datos
│   ├── urls.py                      # Enrutador principal del sistema
│   └── wsgi.py / asgi.py            # Interfaces de servidores de despliegue
│
└── sic_webapp/                      # Aplicación Principal del Sistema Contable
    ├── models.py                    # Entidades relacionales (Cuentas, Transacciones, Movimientos)
    ├── forms.py                     # Formularios con validaciones contables de servidor
    ├── views.py                     # Lógica de negocio (Cálculos de saldos y balances)
    ├── urls.py                      # Rutas locales de la aplicación web
    │
    ├── templatetags/                # Filtros personalizados de Django para plantillas
    │   └── math_extras.py           # Operaciones matemáticas y formateo de monedas
    │
    ├── static/                      # Recursos estáticos de la interfaz de usuario
    │   ├── css/                     # Hojas de estilo estructuradas por módulos contables
    │   └── js/                      # Lógica de interacción en el registro (registrarTransaccion.js)
    │
    ├── templates/                   # Capa visual (Vistas HTML con motor de Django)
    │   ├── base.html                # Plantilla maestra de estructura e interfaz global
    │   ├── home.html                # Panel principal o Dashboard del sistema
    │   └── [estados/balances].html  # Estructuras de reportería contable detallada
    │
    └── tests/                       # Módulo de Pruebas Unitarias
        └── test_balance_general.py  # Test para asegurar el cuadre del balance general
```

## ⚙️ Instalación

```bash
# Clonar el repositorio
git clone https://github.com/melodian1111/SIC115-project.git

# Entrar al directorio
cd SIC115-project

# Crear y activar entorno virtual
python -m venv venv
py -m venv venv            # Si no funciona con python
source venv/bin/activate   # En Linux/Mac
venv\Scripts\activate      # En Windows

# Instalar dependencias
pip install -r requirements.txt
