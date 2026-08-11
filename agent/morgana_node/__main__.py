"""Redirige el antiguo comando del agente al paquete canónico de Vibi."""

try:
    from agent.vibi_node.__main__ import main
except ModuleNotFoundError:  # Ejecución desde el directorio agent/.
    from vibi_node.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
