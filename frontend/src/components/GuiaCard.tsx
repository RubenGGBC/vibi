import { useEffect, useState } from "react";

import { apiBlob } from "../lib/api";
import type { Guia } from "../types";

/**
 * Una guía: la pantalla del usuario con un recuadro numerado sobre cada cosa
 * de la que Vibi está hablando.
 *
 * **Las marcas se dibujan aquí y no vienen pintadas en el JPEG.** El nodo manda
 * la foto limpia y la geometría, y el recuadro es un SVG por encima: así se ve
 * nítido en un móvil que amplía la imagen, y cambiar cómo se señala no obliga a
 * actualizar el agente que corre en la máquina de cada uno.
 *
 * La imagen se pide con el token —igual que los archivos— porque es una foto de
 * su pantalla y su URL está autenticada. Y no se guarda en ningún sitio: caduca
 * en el servidor, así que un fallo al cargarla es lo normal pasado un rato y se
 * dice con esas palabras, no como un error.
 */
export function GuiaCard({ guia }: { guia: Guia }) {
  const [imagen, setImagen] = useState<string | null>(null);
  const [caducada, setCaducada] = useState(false);

  useEffect(() => {
    let vigente = true;
    let url = "";
    void apiBlob(guia.imagen_url)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        if (vigente) setImagen(url);
        else URL.revokeObjectURL(url);
      })
      .catch(() => {
        if (vigente) setCaducada(true);
      });
    return () => {
      vigente = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [guia.imagen_url]);

  if (caducada) {
    return (
      <p className="guia-caducada">
        Esta guía ya no está: las fotos de tu pantalla no se guardan. Pídemela
        otra vez y te la vuelvo a señalar.
      </p>
    );
  }

  return (
    <figure className="guia">
      <div className="guia-lienzo">
        {imagen && (
          <img
            src={imagen}
            alt={`Tu pantalla, con ${guia.marcas.length} sitio(s) señalado(s) en ${
              guia.ventana || "la ventana de delante"
            }`}
          />
        )}
        {/* El SVG comparte el sistema de coordenadas de la foto, así que las
            marcas siguen a su sitio pase lo que pase con el tamaño. */}
        <svg
          className="guia-marcas"
          viewBox={`0 0 ${guia.ancho} ${guia.alto}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {guia.marcas.map((marca) => (
            <g key={marca.numero}>
              <rect
                x={marca.x}
                y={marca.y}
                width={marca.ancho}
                height={marca.alto}
                rx={4}
              />
              <circle cx={marca.x} cy={marca.y} r={13} />
              <text x={marca.x} y={marca.y + 5}>
                {marca.numero}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <figcaption>
        <ol className="guia-leyenda">
          {guia.marcas.map((marca) => (
            <li key={marca.numero}>
              <span className="guia-numero">{marca.numero}</span>
              <span className="guia-que">
                {marca.texto || marca.nombre || marca.rol}
              </span>
            </li>
          ))}
        </ol>
        {guia.fuera.length > 0 && (
          <p className="guia-fuera">
            No se veía en esa pantalla: {guia.fuera.join(", ")}.
          </p>
        )}
      </figcaption>
    </figure>
  );
}
