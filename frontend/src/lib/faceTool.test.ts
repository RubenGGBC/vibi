import { describe, expect, it } from "vitest";

import { caraDeHerramienta } from "./faceTool";

/** Comodidad: solo la cara, que es lo que se afirma casi siempre. */
const cara = (nombre: string) => caraDeHerramienta(nombre).cara;

describe("clasificar la herramienta en marcha", () => {
  it("separa buscar en internet de rebuscar en el disco", () => {
    // Antes las dos ponían la misma cara, aunque el texto de debajo ya las
    // distinguía. Son cosas distintas y se hacen de manera distinta.
    expect(cara("SEARCH_WEB")).toBe("searching");
    expect(cara("WebSearch")).toBe("searching");
    expect(cara("Glob")).toBe("rummaging");
    expect(cara("Grep")).toBe("rummaging");
    expect(cara("list_directory")).toBe("rummaging");
    expect(cara("files_search")).toBe("rummaging");
  });

  it("separa mirar tu pantalla de manejarla", () => {
    expect(cara("screenshot")).toBe("peeking");
    expect(cara("ui_snapshot")).toBe("peeking");
    expect(cara("ui_click")).toBe("handling");
    expect(cara("ui_batch")).toBe("handling");
    expect(cara("keyboard_type")).toBe("handling");
    expect(cara("scroll_page")).toBe("handling");
  });

  it("separa abrir algo de mandarlo a otro equipo", () => {
    expect(cara("launch_app")).toBe("launching");
    expect(cara("open_url")).toBe("launching");
    expect(cara("open_path")).toBe("launching");
    expect(cara("send_file")).toBe("sending");
  });

  it("separa tomar nota de escribir un archivo", () => {
    expect(cara("create_note")).toBe("noting");
    expect(cara("Write")).toBe("writing");
    expect(cara("Edit")).toBe("writing");
  });

  it("reconoce el navegador de verdad", () => {
    expect(cara("mcp__playwright__browser_click")).toBe("browsing");
    expect(cara("WebFetch")).toBe("browsing");
  });

  it("reconoce el terminal", () => {
    expect(cara("Bash")).toBe("hacking");
    expect(cara("run_command")).toBe("hacking");
  });

  it("reconoce el trabajo en la malla sin perder qué está haciendo", () => {
    // Un terminal en el PC de al lado sigue siendo un terminal: la cara cuenta
    // la acción y que pase fuera lo lleva el modificador de `remoto`. Solo cae
    // en `reaching` lo que no se puede clasificar mejor.
    expect(cara("pc_shell_run")).toBe("hacking");
    expect(cara("pc_read_file")).toBe("reading");
    expect(cara("devices_list")).toBe("reaching");
  });

  it("deja leer para el final, que es subcadena de medio catálogo", () => {
    // `read` aparece dentro de `browser_read` y de `spread`; si subiera en la
    // lista se comería clasificaciones mejores.
    expect(cara("read_file")).toBe("reading");
    expect(cara("mcp__playwright__browser_read_page")).toBe("browsing");
  });

  it("cae en la genérica cuando no reconoce nada", () => {
    // Los motores estrenan tipos de paso sin avisar. Que llegue crudo y se
    // degrade a «trabajando» es honesto; inventarse una cara, no.
    expect(cara("CORTEX_STEP_TYPE_ALGO_NUEVO")).toBe("working");
    expect(cara("")).toBe("working");
    expect(caraDeHerramienta(null).cara).toBe("working");
    expect(caraDeHerramienta(undefined).cara).toBe("working");
  });

  it("trae siempre un texto que contar debajo", () => {
    for (const nombre of ["Bash", "Glob", "screenshot", "send_file", "loquesea"]) {
      expect(caraDeHerramienta(nombre).copy, nombre).not.toBe("");
    }
  });
});
