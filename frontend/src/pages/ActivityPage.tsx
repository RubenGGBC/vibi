import { useInfiniteQuery } from "@tanstack/react-query";
import {
  Archive,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  FileClock,
  FolderGit2,
  KeyRound,
  MessageCircle,
  MonitorSmartphone,
  RefreshCw,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../lib/api";
import type {
  ActivityCategory,
  ActivityItem,
  ActivityResponse,
  ActivitySummary,
} from "../types";

type CategoryFilter = ActivityCategory | "";

const FILTERS: Array<{ value: CategoryFilter; label: string }> = [
  { value: "", label: "Todo" },
  { value: "tareas", label: "Tareas" },
  { value: "conversacion", label: "Conversación" },
  { value: "archivos", label: "Archivos" },
  { value: "proyectos", label: "Proyectos" },
  { value: "herramientas", label: "Herramientas" },
  { value: "cuenta", label: "Cuenta" },
  { value: "dispositivos", label: "Dispositivos" },
];

const CATEGORY_ICONS: Record<ActivityCategory, LucideIcon> = {
  tareas: Bot,
  conversacion: MessageCircle,
  archivos: Archive,
  proyectos: FolderGit2,
  herramientas: Wrench,
  cuenta: KeyRound,
  dispositivos: MonitorSmartphone,
};

const formatBytes = (bytes: number): string => {
  if (bytes < 1_000) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1_000;
  let unit = units[0];
  for (let index = 1; value >= 1_000 && index < units.length; index += 1) {
    value /= 1_000;
    unit = units[index];
  }
  return `${new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(value)} ${unit}`;
};

const storagePercent = (summary: ActivitySummary): number => {
  if (summary.almacenamiento_cuota_bytes <= 0) return 0;
  return Math.min(
    100,
    Math.round(
      (summary.almacenamiento_usado_bytes /
        summary.almacenamiento_cuota_bytes) *
        100,
    ),
  );
};

const uniqueEvents = (pages: ActivityResponse[]): ActivityItem[] => {
  const seen = new Set<number>();
  return pages.flatMap(({ eventos }) => eventos).filter(({ id }) => {
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
};

function ActivityPulse({ summary }: { summary: ActivitySummary }) {
  const storage = storagePercent(summary);
  return (
    <dl className="activity-vitals" aria-label="Pulso operativo">
      <div className="activity-vital activity-vital-work">
        <dt><Clock3 size={15} /> En curso</dt>
        <dd>{summary.tareas_activas}</dd>
        <small>{summary.tareas_completadas} completadas</small>
      </div>
      <div className="activity-vital activity-vital-decision">
        <dt><CheckCircle2 size={15} /> Tu decisión</dt>
        <dd>{summary.esperando_aprobacion}</dd>
        <small>esperan aprobación</small>
      </div>
      <div className="activity-vital activity-vital-storage">
        <dt><FileClock size={15} /> Archivo</dt>
        <dd>{storage} %</dd>
        <small>
          {formatBytes(summary.almacenamiento_usado_bytes)} de{" "}
          {formatBytes(summary.almacenamiento_cuota_bytes)}
        </small>
        <i style={{ "--activity-level": `${storage}%` } as React.CSSProperties} />
      </div>
      <div className="activity-vital activity-vital-devices">
        <dt><MonitorSmartphone size={15} /> Ventanas</dt>
        <dd>{summary.dispositivos_recientes} / {summary.dispositivos_conocidos}</dd>
        <small>recientes / conocidas</small>
      </div>
    </dl>
  );
}

export function ActivityPage() {
  const [category, setCategory] = useState<CategoryFilter>("");
  const query = useInfiniteQuery({
    queryKey: ["activity", category],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limite: "20" });
      if (category) params.set("categoria", category);
      if (pageParam) params.set("antes_de", String(pageParam));
      return apiFetch<ActivityResponse>(`/api/actividad?${params}`);
    },
    getNextPageParam: (lastPage) => lastPage.siguiente_cursor ?? undefined,
  });
  const pages = query.data?.pages ?? [];
  const summary = pages[0]?.resumen;
  const events = uniqueEvents(pages);

  return (
    <section className="page activity-page">
      <header className="page-header activity-header">
        <div>
          <p className="eyebrow">Registro personal</p>
          <h1>Actividad</h1>
          <p>El rastro de lo que Vibi ha recibido, decidido y completado.</p>
        </div>
        <span className="activity-ledger-mark"><i /> Bitácora viva</span>
      </header>

      {summary ? (
        <ActivityPulse summary={summary} />
      ) : query.isPending ? (
        <div className="activity-vitals activity-vitals-loading" aria-label="Leyendo pulso">
          <i /><i /><i /><i />
        </div>
      ) : null}

      <div className="activity-filter" aria-label="Filtrar actividad">
        {FILTERS.map((filter) => (
          <button
            key={filter.value || "all"}
            type="button"
            aria-pressed={category === filter.value}
            onClick={() => setCategory(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {query.isPending ? (
        <div className="activity-loading" aria-label="Cargando actividad">
          <i /><i /><i />
        </div>
      ) : query.isError && !query.data ? (
        <div className="activity-error" role="alert">
          <RefreshCw size={24} />
          <p>No se pudo leer la actividad. Vuelve a intentarlo.</p>
          <button
            type="button"
            className="secondary-button"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            {query.isFetching ? "Reintentando…" : "Reintentar"}
          </button>
        </div>
      ) : events.length ? (
        <>
          <ol className="activity-timeline" aria-label="Bitácora de actividad">
            {events.map((item) => {
              const Icon = CATEGORY_ICONS[item.categoria];
              const content = (
                <>
                  <span className="activity-node" aria-hidden="true"><Icon size={17} /></span>
                  <div className="activity-entry-copy">
                    <div>
                      <h2>{item.titulo}</h2>
                      <time dateTime={new Date(item.creado_en * 1_000).toISOString()}>
                        {new Intl.DateTimeFormat("es-ES", {
                          dateStyle: "medium",
                          timeStyle: "short",
                        }).format(item.creado_en * 1_000)}
                      </time>
                    </div>
                    <p>{item.detalle}</p>
                  </div>
                  {item.enlace && <ArrowUpRight className="activity-entry-arrow" size={17} />}
                </>
              );
              return (
                <li key={item.id} className={`activity-entry activity-${item.categoria}`}>
                  {item.enlace ? (
                    <Link to={item.enlace} aria-label={`Abrir ${item.titulo}`}>
                      {content}
                    </Link>
                  ) : (
                    <div>{content}</div>
                  )}
                </li>
              );
            })}
          </ol>
          {query.hasNextPage && (
            <button
              type="button"
              className="activity-more secondary-button"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              {query.isFetchingNextPage ? "Leyendo el registro…" : "Cargar anteriores"}
            </button>
          )}
          {query.isFetchNextPageError && (
            <p className="inline-error" role="alert">
              No se pudieron cargar los eventos anteriores. Inténtalo de nuevo.
            </p>
          )}
        </>
      ) : (
        <div className="empty-list activity-empty">
          <Archive size={30} />
          <h2>Aún no hay señales aquí</h2>
          <p>Cambia el filtro o vuelve cuando Vibi haya procesado alguna acción.</p>
        </div>
      )}
    </section>
  );
}
