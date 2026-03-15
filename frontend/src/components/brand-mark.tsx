"use client";

type BrandMarkProps = {
  alt?: string;
  className?: string;
  size?: number;
};

export function BrandMark({ alt = "MedSpeak", className = "", size = 48 }: BrandMarkProps) {
  return (
    <span
      className={`inline-flex items-center justify-center rounded-full border border-[color:var(--brand-ring)] bg-[var(--surface-strong)] p-[3px] shadow-[var(--shadow-soft)] ${className}`}
      style={{ height: size, width: size }}
    >
      <span className="relative h-full w-full overflow-hidden rounded-full bg-white">
        <img
          alt={alt}
          className="h-full w-full object-contain p-[10%]"
          loading="eager"
          src="/Images/logo.png"
        />
      </span>
    </span>
  );
}
