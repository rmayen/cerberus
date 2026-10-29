import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "../../lib/format";

interface FieldShell {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  className?: string;
  /** Visually hide the label but keep it for assistive technology. */
  hideLabel?: boolean;
}

function useDescribe(hint: ReactNode, error: string | null | undefined) {
  const hintId = useId();
  const errorId = useId();
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  return { hintId, errorId, describedBy };
}

export function TextField({
  label,
  hint,
  error,
  className,
  hideLabel,
  ...input
}: FieldShell & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const { hintId, errorId, describedBy } = useDescribe(hint, error);
  return (
    <div className={cn("field", className)}>
      <label htmlFor={id} className={cn("field-label", hideLabel && "sr-only")}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...input}
      />
      {hint && (
        <span id={hintId} className="field-hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} className="field-error">
          {error}
        </span>
      )}
    </div>
  );
}

export function SelectField({
  label,
  hint,
  error,
  className,
  hideLabel,
  children,
  ...select
}: FieldShell & SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  const id = useId();
  const { hintId, errorId, describedBy } = useDescribe(hint, error);
  return (
    <div className={cn("field", className)}>
      <label htmlFor={id} className={cn("field-label", hideLabel && "sr-only")}>
        {label}
      </label>
      <select
        id={id}
        className="select"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...select}
      >
        {children}
      </select>
      {hint && (
        <span id={hintId} className="field-hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} className="field-error">
          {error}
        </span>
      )}
    </div>
  );
}

export function TextareaField({
  label,
  hint,
  error,
  className,
  hideLabel,
  ...area
}: FieldShell & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  const { hintId, errorId, describedBy } = useDescribe(hint, error);
  return (
    <div className={cn("field", className)}>
      <label htmlFor={id} className={cn("field-label", hideLabel && "sr-only")}>
        {label}
      </label>
      <textarea
        id={id}
        className="textarea"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...area}
      />
      {hint && (
        <span id={hintId} className="field-hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} className="field-error">
          {error}
        </span>
      )}
    </div>
  );
}

export function CheckField({
  label,
  hint,
  ...input
}: { label: ReactNode; hint?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  const hintId = useId();
  return (
    <div className="field">
      <label className="check">
        <input type="checkbox" aria-describedby={hint ? hintId : undefined} {...input} />
        <span>{label}</span>
      </label>
      {hint && (
        <span id={hintId} className="field-hint" style={{ paddingLeft: 28 }}>
          {hint}
        </span>
      )}
    </div>
  );
}
