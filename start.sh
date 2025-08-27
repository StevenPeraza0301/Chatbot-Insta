#!/bin/bash

echo "Activando entorno virtual..."
source env/bin/activate

echo "Iniciando Gunicorn con configuración optimizada..."
gunicorn -w 4 -b 0.0.0.0:5000 app:app --timeout 120
