import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, Terminal } from "lucide-react";

import {
  approveNodeOrder,
  describeOrder,
  fetchNodeApprovals,
  nodeApprovalsKey,
  orderPayload,
  rejectNodeOrder,
  removeApproval,
} from "../lib/nodeApprovals";
import type { NodeOrder } from "../types";
// Junto al componente y no en la hoja global: la PWA y la ventana de la
// consola del companion son bundles distintos y las dos lo necesitan.
import "../styles/aprobaciones.css";

/**
 * Lo que Morgana quiere ejecutar en otra de tus máquinas y no ejecutará hasta
 * que digas que sí. Es el único punto del sistema que una inyección de prompt
 * no puede saltarse: el texto puede convencer al modelo, pero no puede pulsar
 * este botón.
 */
export function AprobacionesPanel() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: nodeApprovalsKey,
    queryFn: fetchNodeApprovals,
  });

  const resolver = useMutation({
    mutationFn: async ({
      orderId,
      aprobar,
    }: {
      orderId: string;
      aprobar: boolean;
    }) => {
      if (aprobar) await approveNodeOrder(orderId);
      else await rejectNodeOrder(orderId);
    },
    // La tarjeta desaparece al instante: la orden ya está decidida aunque el
    // comando remoto tarde en contestar.
    onMutate: ({ orderId }) => {
      client.setQueryData<NodeOrder[]>(nodeApprovalsKey, (current) =>
        removeApproval(current, orderId),
      );
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: nodeApprovalsKey });
      void client.invalidateQueries({ queryKey: ["activity"] });
    },
  });

  const ordenes = query.data ?? [];
  if (!ordenes.length) return null;

  return (
    <section className="aprobaciones" aria-label="Órdenes pendientes de aprobación">
      <header className="aprobaciones-head">
        <ShieldAlert size={16} aria-hidden />
        <h2>
          {ordenes.length === 1
            ? "Morgana quiere hacer algo en otro dispositivo"
            : `${ordenes.length} órdenes esperan tu permiso`}
        </h2>
      </header>

      <ul className="aprobaciones-list">
        {ordenes.map((orden) => (
          <li key={orden.id} className={`aprobacion riesgo-${orden.riesgo}`}>
            <p className="aprobacion-que">{describeOrder(orden)}</p>
            <pre className="aprobacion-payload">
              <Terminal size={13} aria-hidden />
              <code>{orderPayload(orden)}</code>
            </pre>
            {orden.motivo ? (
              <p className="aprobacion-motivo">{orden.motivo}</p>
            ) : null}
            <div className="aprobacion-acciones">
              <button
                type="button"
                className="ghost"
                disabled={resolver.isPending}
                onClick={() =>
                  resolver.mutate({ orderId: orden.id, aprobar: false })
                }
              >
                Rechazar
              </button>
              <button
                type="button"
                className="primary"
                disabled={resolver.isPending}
                onClick={() =>
                  resolver.mutate({ orderId: orden.id, aprobar: true })
                }
              >
                Ejecutar
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
