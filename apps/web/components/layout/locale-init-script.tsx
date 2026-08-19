const localeInitializationScript = `
  (function () {
    var storageKey = "ai-career-agent:locale:v1";
    try {
      var storedLocale = window.localStorage.getItem(storageKey);
      if (storedLocale === "en" || storedLocale === "ar") {
        document.documentElement.lang = storedLocale;
        document.documentElement.dir = storedLocale === "ar" ? "rtl" : "ltr";
      }
    } catch (error) {
      // Keep the server-rendered Arabic default when storage is unavailable.
    }
  })();
`;

// Mirrors ThemeInitScript: applies the stored locale's lang/dir before first paint so a
// returning English user does not get an RTL layout flash on every navigation.
export function LocaleInitScript() {
  return <script id="locale-init" dangerouslySetInnerHTML={{ __html: localeInitializationScript }} />;
}
