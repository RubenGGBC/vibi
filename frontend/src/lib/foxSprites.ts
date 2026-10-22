import sheetUrl from "../../../vibiNewDesign/Pixel Fox Animation Sprite Sheet.png";
import portraitUrl from "../../../vibiNewDesign/Pixel Fox Wizard on Dark Background.png";
import actionsUrl from "../../../vibiNewDesign/Pixel Fox Animation Reference Sheet.png";

export const FOX_WIDTH = 176;
export const FOX_HEIGHT = 232;

// The reference is a presentation sheet, not a regular atlas: exclude the
// captions and numbers, and keep a shared ground line for all eight poses.
const rows = [{ top: 112, bottom: 295 }, { top: 386, bottom: 607 }, { top: 731, bottom: 912 }];
const columns = [205, 367, 529, 691, 861, 1021, 1189, 1349, 1505];

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("No se ha podido cargar el sprite de Vibi."));
    image.src = url;
  });
}

function cutout(image: HTMLImageElement, x: number, y: number, width: number, height: number) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d")!;
  context.drawImage(image, x, y, width, height, 0, 0, width, height);
  const pixels = context.getImageData(0, 0, width, height);
  const barrier = new Uint8Array(width * height);
  const isBackground = (index: number) => {
    const offset = index * 4;
    const r = pixels.data[offset], g = pixels.data[offset + 1], b = pixels.data[offset + 2];
    return Math.max(r, g, b) <= 43 && Math.max(r, g, b) - Math.min(r, g, b) <= 14;
  };
  // Close tiny gaps in the outline before flooding so the sheet's nearly
  // black face remains opaque, even where it meets the black background.
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (isBackground(y * width + x)) continue;
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
      const nx = x + dx, ny = y + dy;
      if (nx >= 0 && nx < width && ny >= 0 && ny < height) barrier[ny * width + nx] = 1;
    }
  }
  const visited = new Uint8Array(width * height);
  const queue: number[] = [];
  const enqueue = (index: number) => {
    if (visited[index]) return;
    visited[index] = 1;
    // Only flood neutral dark pixels connected to the outside. A global
    // chroma key would also erase the black face and the little paws.
    if (barrier[index]) return;
    pixels.data[index * 4 + 3] = 0;
    queue.push(index);
  };
  for (let x = 0; x < width; x++) { enqueue(x); enqueue((height - 1) * width + x); }
  for (let y = 0; y < height; y++) { enqueue(y * width); enqueue(y * width + width - 1); }
  for (let cursor = 0; cursor < queue.length; cursor++) {
    const index = queue[cursor];
    if (index % width > 0) enqueue(index - 1);
    if (index % width < width - 1) enqueue(index + 1);
    if (index >= width) enqueue(index - width);
    if (index < width * (height - 1)) enqueue(index + width);
  }
  context.putImageData(pixels, 0, 0);
  return canvas;
}

export type FoxAction = "internet" | "terminal" | "error";
export type FoxActions = Record<FoxAction, HTMLCanvasElement[]>;
export type FoxSprites = { animations: HTMLCanvasElement[][]; portrait: HTMLCanvasElement; actions: FoxActions };
export type FoxAnimations = FoxSprites["animations"];
let animationCache: Promise<FoxAnimations> | undefined;
let cache: Promise<FoxSprites> | undefined;
let actionCache: Promise<FoxActions> | undefined;

export function loadFoxActions(): Promise<FoxActions> {
  if (!actionCache) {
    actionCache = loadImage(actionsUrl).then((sheet) => {
      const definitions: Array<{ name: FoxAction; top: number; bottom: number; captionBottom: number; columns: number[] }> = [
        { name: "internet", top: 96, bottom: 344, captionBottom: 176, columns: [50, 224, 414, 596, 778, 946, 1118, 1283, 1424] },
        { name: "terminal", top: 418, bottom: 672, captionBottom: 500, columns: [50, 224, 414, 596, 778, 946, 1118, 1283, 1424] },
        { name: "error", top: 752, bottom: 974, captionBottom: 807, columns: [50, 224, 412, 576, 746, 945, 1083, 1263, 1424] },
      ];
      // A common scale and ground line keep the character still while its
      // hat rises. Leave enough room for the globe, terminal and loose hat.
      const scale = (FOX_HEIGHT - 12) / 254;
      return Object.fromEntries(definitions.map(({ name, top, bottom, captionBottom, columns }) => [name,
        Array.from({ length: 8 }, (_, i) => {
          const crop = cutout(sheet, columns[i], top, columns[i + 1] - columns[i], bottom - top);
          if (i === 0) crop.getContext("2d")!.clearRect(0, 0, crop.width, captionBottom - top);
          const frame = document.createElement("canvas");
          frame.width = FOX_WIDTH;
          frame.height = FOX_HEIGHT;
          const width = Math.round(crop.width * scale);
          const height = Math.round(crop.height * scale);
          const context = frame.getContext("2d")!;
          context.imageSmoothingEnabled = false;
          context.drawImage(crop, Math.floor((FOX_WIDTH - width) / 2), FOX_HEIGHT - height - 6, width, height);
          return frame;
        }),
      ])) as FoxActions;
    }).catch((error: unknown) => { actionCache = undefined; throw error; });
  }
  return actionCache;
}

export function loadFoxAnimations(): Promise<FoxAnimations> {
  if (!animationCache) {
    animationCache = loadImage(sheetUrl).then((sheet) =>
      rows.map(({ top, bottom }, row) => Array.from({ length: 8 }, (_, i) => {
        const crop = cutout(sheet, columns[i], top, columns[i + 1] - columns[i], bottom - top);
        // The long “ESTIRAMIENTO” caption slightly overlaps the first cell.
        if (row === 1 && i === 0) crop.getContext("2d")!.clearRect(0, 0, 22, 45);
        const frame = document.createElement("canvas");
        frame.width = FOX_WIDTH;
        frame.height = FOX_HEIGHT;
        frame.getContext("2d")!.drawImage(crop, Math.floor((FOX_WIDTH - crop.width) / 2), FOX_HEIGHT - crop.height - 6);
        return frame;
      })),
    ).catch((error: unknown) => { animationCache = undefined; throw error; });
  }
  return animationCache;
}

export function loadFoxSprites(): Promise<FoxSprites> {
  if (!cache) {
    cache = Promise.all([loadFoxAnimations(), loadImage(portraitUrl), loadFoxActions()]).then(([animations, portrait, actions]) => ({
      animations,
      actions,
      portrait: cutout(portrait, 310, 230, 680, 820),
    })).catch((error: unknown) => { cache = undefined; throw error; });
  }
  return cache;
}
