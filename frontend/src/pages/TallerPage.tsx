import { NavLink, Outlet } from "react-router-dom";

/**
 * El cajón de lo que no es el camino diario.
 *
 * El rail anterior gastaba dos de sus seis huecos en Skills y Tools, que son
 * **configuración del agente**, y otro en Proyectos y otro en Archivos, que son
 * materiales. Cuatro de seis para cosas que se tocan de vez en cuando, mientras
 * el trabajo vivo no tenía ninguno.
 *
 * Aquí dentro no se ha cambiado nada: son las mismas páginas de siempre, a un
 * clic en vez de a cero. Actividad entra también porque es el registro de lo ya
 * pasado — no es trabajo en curso, y en el rail competía con lo que sí lo es.
 */

const PESTANAS = [
  { to: "/taller/actividad", label: "Actividad" },
  { to: "/taller/perfil", label: "Perfil" },
  { to: "/taller/proyectos", label: "Proyectos" },
  { to: "/taller/skills", label: "Skills" },
  { to: "/taller/herramientas", label: "Herramientas" },
  { to: "/taller/archivos", label: "Archivos" },
];

export function TallerPage() {
  return (
    <section className="taller-page" aria-label="Taller">
      <nav className="taller-tabs" aria-label="Secciones del taller">
        {PESTANAS.map(({ to, label }) => (
          <NavLink key={to} to={to} className="taller-tab">
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="taller-cuerpo">
        <Outlet />
      </div>
    </section>
  );
}
