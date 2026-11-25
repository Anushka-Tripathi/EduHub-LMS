// Quiz countdown. The server enforces the real limit; this only shows it and submits at zero.
(function () {
  var el = document.getElementById('timer'), form = document.getElementById('quiz-form');
  if (!el) return;
  var left = parseInt(el.dataset.seconds, 10), submitted = false;
  form.addEventListener('submit', function () { submitted = true; });
  function draw() {
    el.textContent = ('0' + Math.floor(left / 60)).slice(-2) + ':' + ('0' + (left % 60)).slice(-2);
    el.classList.toggle('low', left <= 60);
    if (left <= 0 && !submitted) { submitted = true; form.submit(); return; }
    left -= 1; setTimeout(draw, 1000);
  }
  window.addEventListener('beforeunload', function (e) { if (!submitted) { e.preventDefault(); e.returnValue = ''; } });
  draw();
})();
