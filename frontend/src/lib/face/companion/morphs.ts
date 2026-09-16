import type { FaceState } from "../estados";

export type CompanionMorph =
  | "magnifier"
  | "terminal"
  | "tool"
  | "browser"
  | "folder"
  | "book"
  | "pen"
  | "note"
  | "camera"
  | "mouse"
  | "rocket"
  | "envelope"
  | "dish"
  | "speaker"
  | "anvil"
  | "pod";

export const MORPH_VISUALS: Record<CompanionMorph, string> = {
  magnifier: `
    <g class="morph-object morph-magnifier">
      <path class="magnifier-handle-shadow" d="M267 247 L352 332" />
      <path class="magnifier-handle" d="M267 247 L352 332" />
      <circle class="magnifier-rim-shadow" cx="202" cy="181" r="100" />
      <circle class="magnifier-rim" cx="202" cy="181" r="96" />
      <circle class="magnifier-glass" cx="202" cy="181" r="78" />
      <g class="morph-eyes magnifier-eyes">
        <rect x="166" y="158" width="20" height="47" rx="10" />
        <rect x="218" y="154" width="20" height="47" rx="10" />
      </g>
      <path class="magnifier-glint" d="M145 119 C161 103 183 94 205 94" />
      <g class="magnifier-results">
        <circle cx="296" cy="105" r="5" />
        <circle cx="315" cy="125" r="3.5" />
        <path d="M300 146 H337 M305 158 H329" />
      </g>
    </g>
  `,
  terminal: `
    <g class="morph-object morph-terminal">
      <rect class="terminal-frame-shadow" x="48" y="91" width="324" height="223" rx="24" />
      <rect class="terminal-frame" x="48" y="91" width="324" height="223" rx="24" />
      <path class="terminal-divider" d="M49 132 H371" />
      <circle class="terminal-dot terminal-dot-red" cx="75" cy="112" r="6" />
      <circle class="terminal-dot" cx="95" cy="112" r="6" />
      <circle class="terminal-dot" cx="115" cy="112" r="6" />
      <g class="morph-eyes terminal-eyes">
        <rect x="111" y="175" width="58" height="13" rx="6.5" />
        <path d="M235 155 L270 181 L235 207 L224 194 L243 181 L224 168 Z" />
      </g>
      <g class="terminal-output-lines">
        <path d="M91 240 H177" />
        <path d="M91 262 H250" />
        <path class="terminal-success" d="M91 284 H213" />
        <rect x="263" y="252" width="10" height="18" rx="2" />
      </g>
    </g>
  `,
  tool: `
    <g class="morph-object morph-tool">
      <g class="tool-teeth">
        <rect x="192" y="54" width="36" height="58" rx="9" />
        <rect x="192" y="54" width="36" height="58" rx="9" transform="rotate(45 210 188)" />
        <rect x="192" y="54" width="36" height="58" rx="9" transform="rotate(90 210 188)" />
        <rect x="192" y="54" width="36" height="58" rx="9" transform="rotate(135 210 188)" />
        <rect x="192" y="54" width="36" height="58" rx="9" transform="rotate(180 210 188)" />
        <rect x="192" y="54" width="36" height="58" rx="9" transform="rotate(225 210 188)" />
        <rect x="192" y="54" width="36" height="58" rx="9" transform="rotate(270 210 188)" />
        <rect x="192" y="54" width="36" height="58" rx="9" transform="rotate(315 210 188)" />
      </g>
      <circle class="tool-shell-shadow" cx="210" cy="188" r="107" />
      <circle class="tool-shell" cx="210" cy="188" r="101" />
      <circle class="tool-face" cx="210" cy="188" r="73" />
      <g class="morph-eyes tool-eyes">
        <rect x="169" y="161" width="20" height="48" rx="10" />
        <path d="M222 177 C236 194 255 194 269 177 L261 165 C250 178 240 178 230 165 Z" />
      </g>
      <g class="tool-circuit">
        <circle cx="210" cy="124" r="5" />
        <circle cx="154" cy="221" r="5" />
        <circle cx="267" cy="221" r="5" />
        <path d="M210 129 V143 M159 218 L177 208 M262 218 L244 208" />
      </g>
      <g class="tool-sparks">
        <path d="M311 95 L326 78 M325 110 H346 M296 82 V59" />
      </g>
    </g>
  `,
  browser: `
    <g class="morph-object morph-browser">
      <rect class="browser-shell-shadow" x="47" y="82" width="326" height="235" rx="25" />
      <rect class="browser-shell" x="47" y="82" width="326" height="235" rx="25" />
      <path class="browser-divider" d="M48 127 H372" />
      <circle class="browser-dot browser-dot-red" cx="75" cy="104" r="6" />
      <circle class="browser-dot" cx="95" cy="104" r="6" />
      <circle class="browser-dot" cx="115" cy="104" r="6" />
      <rect class="browser-address" x="138" y="94" width="205" height="21" rx="10.5" />
      <g class="morph-eyes browser-eyes">
        <rect x="131" y="164" width="21" height="48" rx="10.5" />
        <rect x="183" y="160" width="21" height="48" rx="10.5" />
      </g>
      <g class="browser-results">
        <rect x="242" y="157" width="82" height="12" rx="6" />
        <rect x="242" y="181" width="62" height="8" rx="4" />
        <rect x="242" y="205" width="91" height="8" rx="4" />
        <path class="browser-scan" d="M89 245 H333" />
        <rect x="89" y="264" width="104" height="9" rx="4.5" />
        <rect x="89" y="284" width="171" height="7" rx="3.5" />
      </g>
    </g>
  `,
  folder: `
    <g class="morph-object morph-folder">
      <path class="folder-shadow" d="M57 124 Q57 101 80 101 H158 L181 78 H258 Q278 78 281 101 H340 Q363 101 363 124 V298 Q363 318 341 318 H79 Q57 318 57 298 Z" />
      <path class="folder-back" d="M57 124 Q57 101 80 101 H158 L181 78 H258 Q278 78 281 101 H340 Q363 101 363 124 V298 H57 Z" />
      <path class="folder-front" d="M57 163 Q57 143 78 143 H342 Q363 143 363 163 V298 Q363 318 341 318 H79 Q57 318 57 298 Z" />
      <g class="morph-eyes folder-eyes">
        <rect x="157" y="204" width="21" height="49" rx="10.5" />
        <rect x="211" y="200" width="21" height="49" rx="10.5" />
      </g>
      <g class="folder-files">
        <path d="M105 155 V111 H179 L196 128 H305 V155" />
        <path d="M125 142 V99 H201 L216 115 H323 V151" />
      </g>
      <path class="folder-search-line" d="M111 281 H306" />
    </g>
  `,
  book: `
    <g class="morph-object morph-book">
      <path class="book-cover" d="M42 111 Q119 83 205 126 Q291 83 378 111 V310 Q292 282 205 323 Q119 282 42 310 Z" />
      <path class="book-page book-page-left" d="M55 99 Q130 75 205 119 V302 Q130 263 55 292 Z" />
      <path class="book-page book-page-right" d="M205 119 Q280 75 365 99 V292 Q280 263 205 302 Z" />
      <path class="book-spine" d="M205 119 V302" />
      <g class="morph-eyes book-eyes">
        <rect x="132" y="166" width="20" height="47" rx="10" />
        <rect x="263" y="162" width="20" height="47" rx="10" />
      </g>
      <g class="book-lines">
        <path d="M86 238 H169 M91 258 H158 M247 236 H333 M255 257 H323" />
      </g>
      <path class="book-mark" d="M205 285 L220 331 L205 322 L190 331 Z" />
    </g>
  `,
  pen: `
    <g class="morph-object morph-pen">
      <g class="pen-shape" transform="rotate(-35 210 190)">
        <path class="pen-shadow" d="M63 154 Q63 126 92 126 H326 Q354 126 354 154 V226 Q354 254 326 254 H92 Q63 254 63 226 Z" />
        <path class="pen-body" d="M89 132 H326 Q348 132 348 154 V226 Q348 248 326 248 H89 Z" />
        <path class="pen-nib" d="M89 132 L34 190 L89 248 Z" />
        <path class="pen-nib-core" d="M55 190 H89" />
        <path class="pen-cap" d="M304 132 H338 Q355 132 355 150 V230 Q355 248 338 248 H304 Z" />
        <g class="morph-eyes pen-eyes">
          <rect x="151" y="161" width="20" height="47" rx="10" />
          <path d="M198 177 C211 193 229 193 242 177 L234 165 C224 177 215 177 206 165 Z" />
        </g>
        <g class="pen-ink-lines">
          <path d="M119 224 H182 M253 215 H284" />
        </g>
      </g>
      <path class="pen-writing-line" d="M75 306 C151 327 244 326 344 292" />
    </g>
  `,
  note: `
    <g class="morph-object morph-note-object">
      <path class="note-shadow" d="M85 58 H326 Q348 58 348 80 V277 L287 338 H85 Q63 338 63 316 V80 Q63 58 85 58 Z" />
      <path class="note-sheet" d="M85 58 H326 Q348 58 348 80 V277 L287 338 H85 Q63 338 63 316 V80 Q63 58 85 58 Z" />
      <path class="note-fold" d="M287 338 V292 Q287 277 303 277 H348" />
      <path class="note-rule note-rule-red" d="M103 116 H302" />
      <g class="morph-eyes note-eyes">
        <rect x="139" y="153" width="20" height="48" rx="10" />
        <rect x="197" y="149" width="20" height="48" rx="10" />
      </g>
      <g class="note-rules">
        <path d="M104 232 H302 M104 258 H275 M104 284 H240" />
      </g>
      <circle class="note-pin" cx="303" cy="91" r="12" />
    </g>
  `,
  camera: `
    <g class="morph-object morph-camera">
      <path class="camera-shadow" d="M70 125 H126 L149 91 H257 L280 125 H350 Q371 125 371 147 V294 Q371 316 349 316 H71 Q49 316 49 294 V147 Q49 125 70 125 Z" />
      <path class="camera-shell" d="M70 125 H126 L149 91 H257 L280 125 H350 Q371 125 371 147 V294 Q371 316 349 316 H71 Q49 316 49 294 V147 Q49 125 70 125 Z" />
      <circle class="camera-lens-rim" cx="210" cy="221" r="88" />
      <circle class="camera-lens" cx="210" cy="221" r="67" />
      <g class="morph-eyes camera-eyes">
        <rect x="178" y="195" width="19" height="45" rx="9.5" />
        <rect x="224" y="191" width="19" height="45" rx="9.5" />
      </g>
      <rect class="camera-flash" x="302" y="148" width="40" height="24" rx="6" />
      <circle class="camera-record" cx="92" cy="158" r="9" />
      <g class="camera-focus">
        <path d="M137 162 V142 H157 M263 142 H283 V162 M137 278 V298 H157 M263 298 H283 V278" />
      </g>
    </g>
  `,
  mouse: `
    <g class="morph-object morph-mouse">
      <path class="mouse-shadow" d="M210 42 C292 42 337 101 337 189 V236 C337 310 287 342 210 342 C133 342 83 310 83 236 V189 C83 101 128 42 210 42 Z" />
      <path class="mouse-shell" d="M210 42 C292 42 337 101 337 189 V236 C337 310 287 342 210 342 C133 342 83 310 83 236 V189 C83 101 128 42 210 42 Z" />
      <path class="mouse-divider" d="M210 48 V135 M89 164 H331" />
      <rect class="mouse-wheel" x="198" y="74" width="24" height="50" rx="12" />
      <path class="mouse-face" d="M111 174 H309 V271 Q309 311 269 311 H151 Q111 311 111 271 Z" />
      <g class="morph-eyes mouse-eyes">
        <rect x="163" y="210" width="20" height="47" rx="10" />
        <path d="M213 226 C227 243 246 243 260 226 L252 214 C241 227 231 227 221 214 Z" />
      </g>
      <g class="mouse-clicks"><path d="M352 119 L372 99 M362 138 H390 M337 105 V77" /></g>
    </g>
  `,
  rocket: `
    <g class="morph-object morph-rocket">
      <path class="rocket-shadow" d="M210 36 C276 75 298 145 287 236 L337 292 L278 304 L244 267 H176 L142 304 L83 292 L133 236 C122 145 144 75 210 36 Z" />
      <path class="rocket-shell" d="M210 36 C276 75 298 145 287 236 L337 292 L278 304 L244 267 H176 L142 304 L83 292 L133 236 C122 145 144 75 210 36 Z" />
      <path class="rocket-face" d="M147 132 Q210 100 273 132 V232 Q210 265 147 232 Z" />
      <g class="morph-eyes rocket-eyes">
        <rect x="174" y="161" width="20" height="47" rx="10" />
        <rect x="226" y="157" width="20" height="47" rx="10" />
      </g>
      <circle class="rocket-port" cx="210" cy="94" r="18" />
      <g class="rocket-flame">
        <path d="M176 275 C167 316 187 339 210 354 C233 339 253 316 244 275 Z" />
        <path d="M190 282 C190 310 200 325 210 334 C220 325 230 310 230 282 Z" />
      </g>
      <g class="rocket-speed"><path d="M76 180 H42 M82 208 H57 M344 180 H378" /></g>
    </g>
  `,
  envelope: `
    <g class="morph-object morph-envelope">
      <rect class="envelope-shadow" x="45" y="91" width="330" height="230" rx="25" />
      <rect class="envelope-shell" x="45" y="91" width="330" height="230" rx="25" />
      <path class="envelope-flap" d="M56 108 L210 229 L364 108" />
      <path class="envelope-folds" d="M55 307 L165 205 M365 307 L255 205" />
      <path class="envelope-face" d="M111 215 Q210 265 309 215 V293 H111 Z" />
      <g class="morph-eyes envelope-eyes">
        <rect x="168" y="241" width="19" height="44" rx="9.5" />
        <rect x="220" y="237" width="19" height="44" rx="9.5" />
      </g>
      <g class="envelope-speed"><path d="M25 145 H-14 M31 177 H6 M394 251 H363 M406 278 H374" /></g>
      <circle class="envelope-seal" cx="210" cy="204" r="19" />
    </g>
  `,
  dish: `
    <g class="morph-object morph-dish">
      <path class="dish-shadow" d="M71 82 C95 209 172 275 293 292 C305 190 238 102 71 82 Z" />
      <path class="dish-shell" d="M71 82 C95 209 172 275 293 292 C305 190 238 102 71 82 Z" />
      <path class="dish-face" d="M101 117 C131 208 190 250 263 263 C263 191 207 133 101 117 Z" />
      <g class="morph-eyes dish-eyes">
        <rect x="158" y="170" width="19" height="44" rx="9.5" transform="rotate(-28 168 192)" />
        <rect x="207" y="185" width="19" height="44" rx="9.5" transform="rotate(-28 217 207)" />
      </g>
      <path class="dish-arm" d="M247 258 L322 179" />
      <circle class="dish-node" cx="329" cy="171" r="17" />
      <path class="dish-stand" d="M192 273 L164 333 M242 283 L271 333 M146 333 H288" />
      <g class="dish-signal"><path d="M335 137 C359 143 374 158 382 180 M344 104 C388 113 411 141 416 177 M330 162 C339 164 345 170 349 180" /></g>
    </g>
  `,
  speaker: `
    <g class="morph-object morph-speaker">
      <rect class="speaker-shadow" x="80" y="42" width="260" height="304" rx="42" />
      <rect class="speaker-shell" x="80" y="42" width="260" height="304" rx="42" />
      <rect class="speaker-display" x="112" y="77" width="196" height="78" rx="24" />
      <g class="morph-eyes speaker-eyes">
        <rect x="156" y="92" width="18" height="42" rx="9" />
        <path d="M195 107 C208 122 225 122 238 107 L230 96 C221 107 212 107 203 96 Z" />
      </g>
      <circle class="speaker-ring" cx="210" cy="247" r="73" />
      <circle class="speaker-cone" cx="210" cy="247" r="49" />
      <circle class="speaker-core" cx="210" cy="247" r="17" />
      <g class="speaker-waves"><path d="M67 194 C35 220 35 273 67 299 M353 194 C385 220 385 273 353 299 M47 168 C-1 208 -1 286 47 326 M373 168 C421 208 421 286 373 326" /></g>
    </g>
  `,
  anvil: `
    <g class="morph-object morph-anvil">
      <path class="anvil-shadow" d="M46 114 H342 L383 146 L337 181 H273 V236 L312 315 H108 L147 236 V181 H78 Q48 181 36 151 Z" />
      <path class="anvil-shell" d="M46 114 H342 L383 146 L337 181 H273 V236 L312 315 H108 L147 236 V181 H78 Q48 181 36 151 Z" />
      <path class="anvil-face" d="M135 181 H285 V239 Q285 272 252 272 H168 Q135 272 135 239 Z" />
      <g class="morph-eyes anvil-eyes">
        <rect x="169" y="204" width="18" height="42" rx="9" />
        <rect x="222" y="200" width="18" height="42" rx="9" />
      </g>
      <g class="anvil-hammer">
        <rect x="274" y="48" width="98" height="45" rx="12" transform="rotate(-18 323 70)" />
        <path d="M296 86 L250 163" />
      </g>
      <g class="anvil-sparks"><path d="M275 126 L292 107 M291 139 H319 M261 114 V89 M249 129 L230 107" /></g>
      <path class="anvil-glow" d="M133 173 H287" />
    </g>
  `,
  pod: `
    <g class="morph-object morph-pod">
      <path class="pod-shadow" d="M210 35 C292 35 337 126 329 235 C323 321 275 346 210 346 C145 346 97 321 91 235 C83 126 128 35 210 35 Z" />
      <path class="pod-shell" d="M210 35 C292 35 337 126 329 235 C323 321 275 346 210 346 C145 346 97 321 91 235 C83 126 128 35 210 35 Z" />
      <path class="pod-hatch" d="M123 139 Q210 91 297 139 V270 Q210 315 123 270 Z" />
      <g class="morph-eyes pod-eyes">
        <rect x="169" y="163" width="19" height="45" rx="9.5" />
        <path d="M215 179 C229 196 248 196 262 179 L254 167 C243 180 233 180 223 167 Z" />
      </g>
      <path class="pod-desk" d="M143 235 H278 M160 235 V271 M261 235 V271" />
      <g class="pod-gear">
        <circle cx="210" cy="250" r="22" />
        <circle cx="210" cy="250" r="8" />
        <path d="M210 220 V229 M210 271 V280 M180 250 H189 M231 250 H240 M189 229 L195 235 M225 265 L231 271 M231 229 L225 235 M195 265 L189 271" />
      </g>
      <g class="pod-lights">
        <circle cx="151" cy="299" r="7" />
        <circle cx="175" cy="307" r="5" />
        <path d="M241 303 H278" />
      </g>
      <path class="pod-seam" d="M210 42 V104" />
    </g>
  `,
};

export const morphOf = (state: FaceState): CompanionMorph | null => {
  if (state === "searching") return "magnifier";
  if (state === "hacking") return "terminal";
  if (state === "working") return "tool";
  if (state === "browsing") return "browser";
  if (state === "rummaging") return "folder";
  if (state === "reading") return "book";
  if (state === "writing") return "pen";
  if (state === "noting") return "note";
  if (state === "peeking") return "camera";
  if (state === "handling") return "mouse";
  if (state === "launching") return "rocket";
  if (state === "sending") return "envelope";
  if (state === "reaching") return "dish";
  if (state === "vibing") return "speaker";
  if (state === "forjando") return "anvil";
  if (state === "trastienda") return "pod";
  return null;
};

export function mountCompanionMorphs(figure: SVGGElement): void {
  figure.insertAdjacentHTML(
    "afterbegin",
    Object.values(MORPH_VISUALS).join(""),
  );
}
