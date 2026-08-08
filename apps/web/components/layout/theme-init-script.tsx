const themeInitializationScript = `
  (function () {
    var storageKey = "ai-career-agent:theme:v1";
    var theme = "dark";
    try {
      var storedTheme = window.localStorage.getItem(storageKey);
      if (storedTheme === "dark" || storedTheme === "light") {
        theme = storedTheme;
      } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        theme = "light";
      }
    } catch (error) {
      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        theme = "light";
      }
    }
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  })();
`;

export function ThemeInitScript() {
  return <script id="theme-init" dangerouslySetInnerHTML={{ __html: themeInitializationScript }} />;
}
