import { useState, useEffect, useRef, useMemo } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { Button } from '@/components/ui/button';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from 'lucide-react';
import 'react-pdf/dist/esm/Page/AnnotationLayer.css';
import 'react-pdf/dist/esm/Page/TextLayer.css';

// Configure PDF.js worker - use local worker file from public directory
pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';

interface PDFViewerProps {
  file: string | { url: string; httpHeaders?: Record<string, string> };
}

export function PDFViewer({ file }: PDFViewerProps) {
  const fileKey = JSON.stringify(file);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pdfDocumentRef = useRef<PDFDocumentProxy | null>(null);

  // Reset state when URL changes
  useEffect(() => {
    console.log('PDFViewer: File changed:', file);
    setNumPages(null);
    setPageNumber(1);
    setIsLoading(true);
    setError(null);
    pdfDocumentRef.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileKey]); // Use fileKey to detect changes

  function onDocumentLoadSuccess(pdf: PDFDocumentProxy) {
    console.log('PDF loaded successfully:', { numPages: pdf.numPages });
    pdfDocumentRef.current = pdf;
    setNumPages(pdf.numPages);
    setIsLoading(false);
    setError(null);
  }

  function onDocumentLoadError(error: Error) {
    console.error('PDF load error:', error);
    setError(`Failed to load PDF: ${error.message}`);
    setIsLoading(false);
  }

  const goToPrevPage = () => setPageNumber((prev) => Math.max(prev - 1, 1));
  const goToNextPage = () =>
    setPageNumber((prev) => Math.min(prev + 1, numPages || prev));
  const zoomIn = () => setScale((prev) => Math.min(prev + 0.2, 3.0));
  const zoomOut = () => setScale((prev) => Math.max(prev - 0.2, 0.5));

  // Memoize file object to prevent unnecessary re-renders in Document
  const memoizedFile = useMemo(() => {
    return file;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileKey]);

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      <div className="flex items-center justify-between p-4 border-b bg-background/50">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={goToPrevPage}
            disabled={pageNumber <= 1 || isLoading}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>

          <span className="text-sm px-3">
            Page {pageNumber} of {numPages || '...'}
          </span>

          <Button
            variant="outline"
            size="sm"
            onClick={goToNextPage}
            disabled={!numPages || pageNumber >= numPages || isLoading}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={zoomOut}
            disabled={scale <= 0.5 || isLoading}
          >
            <ZoomOut className="h-4 w-4" />
          </Button>

          <span className="text-sm px-2">{Math.round(scale * 100)}%</span>

          <Button
            variant="outline"
            size="sm"
            onClick={zoomIn}
            disabled={scale >= 3.0 || isLoading}
          >
            <ZoomIn className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* PDF Display */}
      <div className="flex-1 overflow-auto bg-muted/20 flex items-center justify-center p-4">
        {error ? (
          <div className="text-center text-destructive">
            <p className="text-lg font-semibold mb-2">Error loading PDF</p>
            <p className="text-sm">{error}</p>
          </div>
        ) : (
          <Document
            key={typeof memoizedFile === 'string' ? memoizedFile : memoizedFile.url}
            file={memoizedFile}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={
              <div className="text-center">
                <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                <p className="mt-2 text-sm text-muted-foreground">Loading PDF...</p>
              </div>
            }
          >
            {numPages && (
              <Page
                pageNumber={pageNumber}
                scale={scale}
                className="shadow-lg"
                loading={
                  <div className="flex items-center justify-center min-h-[400px]">
                    <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                  </div>
                }
                error={
                  <div className="flex items-center justify-center min-h-[400px] text-destructive">
                    <p>Failed to load page {pageNumber}</p>
                  </div>
                }
              />
            )}
          </Document>
        )}
      </div>
    </div>
  );
}
