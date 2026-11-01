import "pdfjs-dist/web/pdf_viewer.css";
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy, TextLayer } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";
import { markTerms } from "./highlight";

GlobalWorkerOptions.workerSrc = workerUrl;

export default function PdfView({ id, page, terms, onMarks, onError }: {
  id: number;
  page: number;
  terms: string[];
  onMarks: (marks: HTMLElement[]) => void;
  onError: () => void;
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const holder = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const text = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const task = getDocument({
      url: `/api/library/documents/${id}/file`,
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/standard_fonts/",
      wasmUrl: "/pdfjs/wasm/",
      disableAutoFetch: true,
    });
    task.promise.then(setPdf).catch(onError);
    return () => { void task.destroy(); };
  }, [id]); // eslint-disable-line

  useEffect(() => {
    if (!pdf || !holder.current || !canvas.current || !text.current) return;
    let cancelled = false;
    let layer: TextLayer | null = null;
    const textDiv = text.current;
    const target = canvas.current;
    const box = holder.current;
    pdf.getPage(page).then(async (pdfPage) => {
      const natural = pdfPage.getViewport({ scale: 1 });
      const scale = Math.min(box.clientWidth / natural.width, 2);
      const viewport = pdfPage.getViewport({ scale });
      target.width = Math.floor(viewport.width);
      target.height = Math.floor(viewport.height);
      box.style.setProperty("--total-scale-factor", String(scale));
      box.style.width = `${target.width}px`;
      box.style.height = `${target.height}px`;
      await pdfPage.render({ canvas: target, viewport }).promise;
      if (cancelled) return;
      textDiv.replaceChildren();
      layer = new TextLayer({
        textContentSource: pdfPage.streamTextContent(), container: textDiv, viewport,
      });
      await layer.render();
      if (!cancelled) onMarks(markTerms(textDiv, terms));
    }).catch(() => { if (!cancelled) onError(); });
    return () => { cancelled = true; layer?.cancel(); };
  }, [pdf, page]); // eslint-disable-line

  return (
    <div ref={holder} className="pdf-page">
      <canvas ref={canvas} />
      <div ref={text} className="textLayer" />
    </div>
  );
}
