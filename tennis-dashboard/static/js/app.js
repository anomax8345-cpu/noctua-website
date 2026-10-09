// Dashboard filtering + auto-refresh + price chart. No external dependencies.
(function () {
  "use strict";

  var table = document.getElementById("matches-table");
  if (table) {
    var search = document.getElementById("search");
    var tourF = document.getElementById("tour-filter");
    var surfaceF = document.getElementById("surface-filter");
    var fEdge3 = document.getElementById("f-edge3");
    var fEdge5 = document.getElementById("f-edge5");
    var fConf = document.getElementById("f-conf");
    var fLiq = document.getElementById("f-liq");

    function apply() {
      var q = (search.value || "").toLowerCase();
      var tour = tourF.value;
      var surface = surfaceF.value;
      table.querySelectorAll("tbody .match-row").forEach(function (row) {
        var text = row.getAttribute("data-text") || "";
        var edge = Math.abs(parseFloat(row.getAttribute("data-edge")) || 0);
        var conf = parseInt(row.getAttribute("data-conf") || "0", 10);
        var liq = row.getAttribute("data-liq");
        var show = true;
        if (q && text.indexOf(q) === -1) show = false;
        if (tour && row.getAttribute("data-tour") !== tour) show = false;
        if (surface && row.getAttribute("data-surface") !== surface) show = false;
        if (fEdge3.checked && edge < 3) show = false;
        if (fEdge5.checked && edge < 5) show = false;
        if (fConf.checked && conf < 75) show = false;
        if (fLiq.checked && liq !== "HIGH") show = false;
        row.style.display = show ? "" : "none";
      });
    }
    [search, tourF, surfaceF, fEdge3, fEdge5, fConf, fLiq].forEach(function (el) {
      if (el) { el.addEventListener("input", apply); el.addEventListener("change", apply); }
    });
  }

  var refresh = parseInt(window.__REFRESH__ || "300", 10);
  if (!isNaN(refresh) && refresh >= 30) {
    setTimeout(function () { location.reload(); }, refresh * 1000);
  }

  var canvas = document.getElementById("price-chart");
  if (canvas && window.__MARKET_ID__) {
    fetch("/api/price-history/" + encodeURIComponent(window.__MARKET_ID__))
      .then(function (r) { return r.json(); })
      .then(function (points) {
        if (!points || points.length < 2) {
          var empty = document.getElementById("price-empty");
          if (empty) empty.style.display = "block";
          canvas.style.display = "none";
          return;
        }
        drawChart(canvas, points);
      })
      .catch(function () {});
  }

  function drawChart(cv, points) {
    var ctx = cv.getContext("2d");
    var w = cv.width = cv.clientWidth;
    var h = cv.height;
    ctx.clearRect(0, 0, w, h);
    var prices = points.map(function (p) { return p.price; });
    var min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
    var pad = 24;
    function x(i) { return pad + (i / (points.length - 1)) * (w - 2 * pad); }
    function y(v) { var r = (v - min) / ((max - min) || 1); return h - pad - r * (h - 2 * pad); }
    ctx.strokeStyle = "#b6e04b"; ctx.lineWidth = 2; ctx.beginPath();
    points.forEach(function (p, i) { i ? ctx.lineTo(x(i), y(p.price)) : ctx.moveTo(x(i), y(p.price)); });
    ctx.stroke();
    ctx.fillStyle = "#8ba599"; ctx.font = "11px sans-serif";
    ctx.fillText((max * 100).toFixed(0) + "%", 2, y(max) + 4);
    ctx.fillText((min * 100).toFixed(0) + "%", 2, y(min) + 4);
  }
})();
