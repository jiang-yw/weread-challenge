(() => {
  let theme = "light";
  try { if (localStorage.getItem("weread-theme") === "dark") theme = "dark"; } catch {}
  document.documentElement.dataset.theme = theme;
  document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll("[data-theme-toggle]");
    function update() {
      const dark = document.documentElement.dataset.theme === "dark";
      buttons.forEach(button => {
        button.textContent = dark ? "切换浅色" : "切换深色";
        button.setAttribute("aria-pressed", String(dark));
      });
    }
    buttons.forEach(button => button.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("weread-theme", next); } catch {}
      update();
    }));
    update();
  });
})();
