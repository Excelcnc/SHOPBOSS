// The artifact viewer's runtime capabilities (declared at publish: sample with images, downloads).
// Each resolves null when this view can't use it: run outside claude.ai, declined, or not offered.
/* eslint-disable @typescript-eslint/no-explicit-any */

const use = (name: string): Promise<any | null> => {
  const c = (window as any).claude;
  if (!c?.use) return Promise.resolve(null);
  return c.use(name).catch(() => null);
};

let sampleP: Promise<any | null> | null = null;
let downloadsP: Promise<any | null> | null = null;
export const getSample = () => (sampleP ??= use("sample"));
export const getDownloads = () => (downloadsP ??= use("downloads"));

/** Viewer-facing text for a failed Claude call. */
export function claudeError(e: any): string {
  switch (e?.code) {
    case "not_granted": case "sampling_disabled": case "not_declared": case "capability_disabled": case "capability_removed":
      return "Claude isn't allowed for this page. You can still enter the details by hand.";
    case "rate_limited": return "Claude is busy or your usage limit was reached. Try again in a few minutes.";
    case "session_expired": return "Your claude.ai session expired. Sign in again, then retry.";
    case "image_rejected": return "Claude couldn't read that image. Try a PDF or a clearer PNG/JPG.";
    case "prompt_too_large": return "That file has too much text for one request. Try a single drawing.";
    case "refused": return "Claude declined to read this file.";
    case "invalid_json": return "Claude's answer couldn't be read. Try again.";
    case "cancelled": return "Stopped.";
    default: return "Claude couldn't answer just now. Try again.";
  }
}

/** Offer a file to the viewer; returns a short status for a toast. */
export async function offerDownload(filename: string, data: Blob | string): Promise<string> {
  const d = await getDownloads();
  if (!d) return "Downloads aren't available in this view (open the page in claude.ai).";
  try {
    const r = await d.save({ filename, data });
    return r?.status === "delivered" ? `Sent ${filename}` : `Saved ${filename}`;
  } catch (e: any) {
    if (e?.code === "declined") return "Download cancelled.";
    if (e?.code === "rate_limited") return "Another download is waiting for your answer.";
    return "Downloads aren't available in this view.";
  }
}

export const dataUrlToBlob = (u: string) => {
  const [head, b64] = u.split(",");
  const type = head.slice(5).split(";")[0];
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type });
};
