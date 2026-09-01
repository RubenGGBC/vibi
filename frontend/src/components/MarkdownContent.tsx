import { Children, isValidElement, type ReactElement } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * El lenguaje del bloque, subido al `<pre>` para que el CSS lo pueda rotular.
 *
 * `react-markdown` lo deja donde manda el estándar —`<code class="language-py">`—
 * y desde ahí no hay forma de escribirlo: `content: attr()` solo lee atributos
 * del propio elemento, nunca de un hijo. Subirlo un nivel es lo que permite que
 * la etiqueta del bloque salga en CSS, sin un componente por lenguaje.
 */
const components: Components = {
  pre({ children, ...props }) {
    const primero = Children.toArray(children)[0];
    const clase =
      isValidElement(primero) &&
      typeof (primero as ReactElement<{ className?: string }>).props.className === "string"
        ? (primero as ReactElement<{ className?: string }>).props.className ?? ""
        : "";
    const lenguaje = /language-([\w+-]+)/.exec(clase)?.[1];
    return (
      <pre {...props} data-lang={lenguaje}>
        {children}
      </pre>
    );
  },
};

export function MarkdownContent({ children }: { children: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
