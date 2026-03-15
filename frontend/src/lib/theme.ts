export type ThemeMode = "light" | "dark";

export const themeStorageKey = "medspeak-theme";

export function getSystemTheme(): ThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getStoredTheme(): ThemeMode | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(themeStorageKey);
  return stored === "dark" || stored === "light" ? stored : null;
}

export function resolveTheme(): ThemeMode {
  return getStoredTheme() ?? getSystemTheme();
}

export function applyTheme(theme: ThemeMode): void {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.dataset.theme = theme;
}

export const themeInitScript = `
  (function () {
    try {
      var key = "${themeStorageKey}";
      var stored = window.localStorage.getItem(key);
      var theme = stored === "dark" || stored === "light"
        ? stored
        : (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      document.documentElement.dataset.theme = theme;
    } catch (error) {
      document.documentElement.dataset.theme = "light";
    }
  })();
`;
