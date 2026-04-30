(function () {
  const yearNode = document.getElementById("footer-year");
  if (yearNode) {
    yearNode.textContent = "(c) " + new Date().getFullYear() + " OFX Simples. Todos os direitos reservados.";
  }
})();
