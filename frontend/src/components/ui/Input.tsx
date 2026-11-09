import { useId, type InputHTMLAttributes } from "react";

export function Input({
  className = "",
  invalid = false,
  placeholder = "",
  id,
  value,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }) {
  const generatedId = useId();
  const inputId = id || rest.name || generatedId;
  const labelText = placeholder || "Enter text";

  return (
    <div className={`input-container ${className}`}>
      <input
        {...rest}
        id={inputId}
        value={value ?? ""}
        placeholder=" "
        aria-invalid={invalid || undefined}
        className="input-field"
        style={{ fontSize: "16px" }}
      />
      <label htmlFor={inputId} className="input-label">
        {labelText}
      </label>
      <span className="input-highlight" />
    </div>
  );
}
