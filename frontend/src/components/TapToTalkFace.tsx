export type TapToTalkState = "idle" | "listening" | "thinking" | "speaking";

/**
 * El gato tocable de `FacePage`, separado para que la entrevista lo reutilice
 * sin duplicar el SVG. Solo dibuja: el estado y qué pasa al tocarlo los decide
 * quien lo monta.
 */
export function TapToTalkFace({
  state,
  onTap,
  disabled = false,
  ariaLabel = "Hablar con Vibi",
}: {
  state: TapToTalkState;
  onTap: () => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      className={`face-stage face-${state}`}
      onClick={onTap}
      disabled={disabled || state === "thinking"}
      aria-label={ariaLabel}
      aria-pressed={state === "listening"}
    >
      <span className="face-halo" aria-hidden="true" />
      <span className="face-ring" aria-hidden="true" />
      <svg
        viewBox="0 0 400 400"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <g className="face-cat">
          <g className="face-ear face-ear-left">
            <path
              d="M94 150 L78 58 Q77 47 88 52 L164 94 Z"
              className="face-fur face-outline"
            />
            <path d="M104 128 L95 74 L140 100 Z" className="face-ear-inner" />
          </g>
          <g className="face-ear face-ear-right">
            <path
              d="M306 150 L322 58 Q323 47 312 52 L236 94 Z"
              className="face-fur face-outline"
            />
            <path d="M296 128 L305 74 L260 100 Z" className="face-ear-inner" />
          </g>

          <ellipse
            cx="200"
            cy="212"
            rx="134"
            ry="126"
            className="face-fur face-outline"
          />
          <path
            className="face-spark"
            d="M200 78 L205.5 90 L218 93 L205.5 96 L200 108 L194.5 96 L182 93 L194.5 90 Z"
          />

          <ellipse className="face-blush" cx="122" cy="238" rx="20" ry="12" />
          <ellipse className="face-blush" cx="278" cy="238" rx="20" ry="12" />

          <g className="face-normal-eyes">
            <g className="face-pupils">
              <g className="face-eye face-eye-left">
                <ellipse cx="152" cy="198" rx="19" ry="24" />
                <circle className="face-shine-primary" cx="159" cy="189" r="6" />
                <circle className="face-shine-secondary" cx="146" cy="205" r="3.5" />
              </g>
              <g className="face-eye face-eye-right">
                <ellipse cx="248" cy="198" rx="19" ry="24" />
                <circle className="face-shine-primary" cx="255" cy="189" r="6" />
                <circle className="face-shine-secondary" cx="242" cy="205" r="3.5" />
              </g>
            </g>
          </g>

          <g className="face-happy-eyes">
            <path d="M134 202 Q152 184 170 202" />
            <path d="M230 202 Q248 184 266 202" />
          </g>

          <path
            d="M191 236 Q200 229 209 236 Q205 247 200 247 Q195 247 191 236 Z"
            className="face-nose"
          />
          <g className="face-resting-mouth">
            <path d="M200 249 Q200 262 186 262 M200 249 Q200 262 214 262" />
          </g>
          <g className="face-speaking-mouth">
            <ellipse cx="200" cy="260" rx="15" ry="13" />
            <ellipse className="face-tongue" cx="200" cy="266" rx="8" ry="5" />
          </g>

          <g className="face-whiskers face-whiskers-left">
            <path d="M114 216 Q84 208 56 194" />
            <path d="M112 232 Q80 230 50 224" />
            <path d="M114 248 Q84 252 58 262" />
          </g>
          <g className="face-whiskers face-whiskers-right">
            <path d="M286 216 Q316 208 344 194" />
            <path d="M288 232 Q320 230 350 224" />
            <path d="M286 248 Q316 252 342 262" />
          </g>

          <g className="face-thinking-dots">
            <circle cx="298" cy="104" r="6" />
            <circle cx="322" cy="84" r="8" />
            <circle cx="348" cy="60" r="10" />
          </g>
        </g>
      </svg>
    </button>
  );
}
