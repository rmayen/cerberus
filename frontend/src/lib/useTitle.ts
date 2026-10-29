import { useEffect } from "react";

/** Set the document title so each page is identifiable in tabs and history. */
export function useTitle(title: string | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · Cerberus` : "Cerberus";
  }, [title]);
}
