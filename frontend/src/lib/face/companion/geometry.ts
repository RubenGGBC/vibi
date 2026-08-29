/** Sistema de coordenadas único del companion y sus hitos visuales. */
export const COMPANION_VIEWBOX = "0 0 420 360";

export const REFERENCE_LANDMARKS = {
  hatTop: { x: 96, y: 28 },
  brimLeft: { x: 38, y: 174 },
  brimRight: { x: 342, y: 112 },
  jawTip: { x: 178, y: 299 },
  flameTip: { x: 369, y: 151 },
} as const;

/**
 * El dibujo maestro, separado de su movimiento.
 *
 * Todas las curvas viven en el mismo lienzo para que sombrero, cara y fuego
 * conserven la diagonal de la lámina al animarse por separado.
 */
export const COMPANION_GEOMETRY = {
  crown:
    "M96 28 C75 30 62 42 69 58 L108 162 " +
    "C154 154 211 138 260 119 L244 42 C240 25 226 18 204 20 Z",
  crownFoldA: "M128 48 C139 80 145 116 147 151",
  crownFoldB: "M151 41 C159 78 164 111 165 145",
  brim:
    "M38 174 C24 154 39 136 69 137 C120 151 193 132 267 101 " +
    "C296 89 326 91 342 112 C314 142 272 167 221 186 " +
    "C150 212 76 207 38 174 Z",
  head:
    "M89 171 C126 151 194 145 254 157 C299 166 322 194 314 229 " +
    "C304 268 255 290 191 300 C145 307 100 283 79 247 " +
    "C62 218 64 185 89 171 Z",
  mask:
    "M61 156 C136 132 251 134 326 169 L320 233 " +
    "C289 222 260 230 231 242 C195 258 156 250 124 233 " +
    "C102 221 81 215 67 220 Z",
  jaw:
    "M77 222 C99 222 120 237 145 248 C180 264 218 263 254 248 " +
    "C276 239 296 235 314 238 C296 270 252 291 191 300 " +
    "C143 306 98 281 77 246 Z",
  mouth: "M135 236 C160 251 188 250 212 230",
  question: "M326 79 C349 69 369 79 368 98 C367 112 350 116 347 131 M344 148 L344 149",
  terminalDash: "M128 218 L167 218",
  terminalChevron: "M211 198 L238 218 L211 238",
  magnifierRing: { cx: 329, cy: 248, r: 25 },
  magnifierHandle: "M347 267 L373 293",
  flameTongues: [
    {
      outer:
        "M303 231 C311 204 307 183 327 165 C325 188 346 193 339 216 " +
        "C334 234 317 246 303 231 Z",
      inner:
        "M317 225 C323 210 321 199 331 188 C330 202 340 207 335 220 " +
        "C331 230 323 233 317 225 Z",
    },
    {
      outer:
        "M325 194 C335 169 337 145 357 126 C352 151 374 156 367 178 " +
        "C362 195 344 207 325 194 Z",
      inner:
        "M341 185 C347 171 347 159 357 148 C355 163 365 168 360 179 " +
        "C356 188 348 191 341 185 Z",
    },
    {
      outer:
        "M348 165 C357 145 358 128 375 114 C372 133 389 137 383 154 " +
        "C378 166 365 175 348 165 Z",
      inner:
        "M361 158 C366 148 366 140 374 132 C373 142 380 146 376 154 " +
        "C373 160 367 162 361 158 Z",
    },
  ],
  eyeAnchors: [
    { x: 142, y: 217 },
    { x: 213, y: 205 },
  ],
} as const;
