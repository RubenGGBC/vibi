import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setApiBase } from "../lib/api";
import { setToken } from "../lib/auth";

import { MascotaChat } from "./MascotaChat";

const ajustes = {
  apiBase: "http://127.0.0.1:8000",
  nodeToken: "nodo.secreto",
  nodeName: "Sobremesa",
  userToken: "jwt.de.usuario",
  userName: "ruben",
};

interface Peticion {
  url: string;
  autorizacion: string | null;
  cuerpo: Record<string, unknown>;
}

const registrar = (peticiones: Peticion[], respuesta: unknown) =>
  vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    peticiones.push({
      url: String(input),
      autorizacion: new Headers(init?.headers).get("Authorization"),
      cuerpo: JSON.parse(String(init?.body ?? "{}")),
    });
    return Response.json(respuesta);
  });

const escribir = () =>
  screen.getByRole("textbox", { name: "Escribe a Vibi" });

describe("el chat de texto de la mascota", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "vibi.companion.settings",
      JSON.stringify(ajustes),
    );
    setApiBase(ajustes.apiBase);
    setToken(ajustes.userToken);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("manda lo escrito a la API con el JWT de usuario y enseña la respuesta", async () => {
    const peticiones: Peticion[] = [];
    vi.stubGlobal(
      "fetch",
      registrar(peticiones, { via: "rapida", respuesta: "Son las nueve." }),
    );

    render(<MascotaChat onCerrar={() => undefined} />);

    // El chat se abre para escribir: si hubiera que pinchar el campo antes,
    // abrirlo desde la mascota no ahorraría nada.
    expect(escribir()).toHaveFocus();

    await userEvent.type(escribir(), "qué hora es{Enter}");

    expect(await screen.findByText("Son las nueve.")).toBeInTheDocument();
    expect(screen.getByText("qué hora es")).toBeInTheDocument();
    expect(peticiones).toHaveLength(1);
    expect(peticiones[0].url).toBe("http://127.0.0.1:8000/api/mensaje");
    // El token de nodo vive en esta máquina y solo vale para voz: lo que viaja
    // aquí es el JWT del usuario, como en la consola.
    expect(peticiones[0].autorizacion).toBe("Bearer jwt.de.usuario");
    expect(peticiones[0].cuerpo.texto).toBe("qué hora es");
    expect(peticiones[0].cuerpo.client_ref).toEqual(expect.any(String));
  });

  it("deja el campo limpio y listo para el siguiente mensaje", async () => {
    vi.stubGlobal(
      "fetch",
      registrar([], { via: "rapida", respuesta: "Hecho." }),
    );

    render(<MascotaChat onCerrar={() => undefined} />);
    await userEvent.type(escribir(), "hola{Enter}");
    expect(await screen.findByText("Hecho.")).toBeInTheDocument();

    expect(escribir()).toHaveValue("");
  });

  it("no manda nada cuando lo escrito está en blanco", async () => {
    const peticiones: Peticion[] = [];
    vi.stubGlobal("fetch", registrar(peticiones, { via: "rapida", respuesta: "" }));

    render(<MascotaChat onCerrar={() => undefined} />);
    await userEvent.type(escribir(), "   {Enter}");

    expect(peticiones).toHaveLength(0);
  });

  it("no repite el mensaje si lo envías otra vez mientras espera respuesta", async () => {
    const peticiones: Peticion[] = [];
    const pendiente: { responder: (() => void) | null } = { responder: null };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        peticiones.push({
          url: String(input),
          autorizacion: null,
          cuerpo: JSON.parse(String(init?.body ?? "{}")),
        });
        return new Promise<Response>((resolve) => {
          pendiente.responder = () =>
            resolve(Response.json({ via: "rapida", respuesta: "Ya está." }));
        });
      }),
    );

    render(<MascotaChat onCerrar={() => undefined} />);
    await userEvent.type(escribir(), "apaga la luz{Enter}");
    expect(peticiones).toHaveLength(1);

    // Un turno puede tardar. Insistir mientras tanto mandaba el encargo dos
    // veces, y apagar la luz dos veces no es lo mismo que apagarla una.
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
    await userEvent.type(escribir(), "apaga la luz{Enter}");
    expect(peticiones).toHaveLength(1);

    pendiente.responder?.();
    expect(await screen.findByText("Ya está.")).toBeInTheDocument();
  });

  it("ofrece iniciar sesión cuando el JWT ha caducado, sin tocar el token de nodo", async () => {
    const peticiones: Peticion[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        peticiones.push({
          url: String(input),
          autorizacion: new Headers(init?.headers).get("Authorization"),
          cuerpo: JSON.parse(String(init?.body ?? "{}")),
        });
        return Response.json({ detail: "Token caducado" }, { status: 401 });
      }),
    );

    render(<MascotaChat onCerrar={() => undefined} />);
    await userEvent.type(escribir(), "hola{Enter}");

    expect(
      await screen.findByText(/sesión.*caducado|caducado.*sesión/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Iniciar sesión" }),
    ).toBeInTheDocument();
    // Reintentar con el token de nodo sería darle a la consola una credencial
    // que solo debe abrir la voz: no se manda nada más.
    expect(peticiones).toHaveLength(1);
    expect(peticiones.every((p) => p.autorizacion !== "Bearer nodo.secreto")).toBe(
      true,
    );
    expect(screen.queryByText(/nodo\.secreto/)).not.toBeInTheDocument();
  });

  it("se cierra sin cerrar la mascota", async () => {
    const cerrado = vi.fn();
    vi.stubGlobal("fetch", registrar([], {}));

    render(<MascotaChat onCerrar={cerrado} />);
    await userEvent.click(screen.getByRole("button", { name: "Cerrar el chat" }));

    expect(cerrado).toHaveBeenCalledTimes(1);
  });

  it("se cierra con Escape como un bocadillo ligero", async () => {
    const cerrado = vi.fn();
    vi.stubGlobal("fetch", registrar([], {}));

    render(<MascotaChat onCerrar={cerrado} />);
    await userEvent.keyboard("{Escape}");

    expect(cerrado).toHaveBeenCalledTimes(1);
  });
});
