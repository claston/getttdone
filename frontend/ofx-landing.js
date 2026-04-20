(function () {
  const yearNode = document.getElementById("footer-year");
  if (yearNode) {
    yearNode.textContent = "(c) " + new Date().getFullYear() + " OFX Simples. Todos os direitos reservados.";
  }

  const menuToggle = document.getElementById("menu-toggle");
  const topLinks = document.getElementById("top-links");
  if (!menuToggle || !topLinks) {
    return;
  }

  menuToggle.addEventListener("click", function () {
    const open = topLinks.classList.toggle("is-open");
    menuToggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
})();
