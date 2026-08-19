"""Abre la ventana del instalador.

Existe como módulo aparte para poder invocarlo con el intérprete del entorno
(`python -m installer`), que es el único que tiene la biblioteca de la ventana.
El `install.py` de la raíz corre con el Python del sistema y no la tiene.
"""
from . import ventana

ventana.abrir()
