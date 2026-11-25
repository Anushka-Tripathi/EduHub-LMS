// Student camera scanner using the browser's BarcodeDetector (Chrome/Edge/Android). Falls back to typing the code.
(function () {
  var btn = document.getElementById('scan-start'), video = document.getElementById('scan-video'), msg = document.getElementById('scan-msg');
  if (!btn) return;
  if (!('BarcodeDetector' in window) || !navigator.mediaDevices) {
    msg.textContent = 'This browser cannot scan inside the page. Use your phone camera app, or type the 6-digit code on the right.';
    btn.disabled = true; return;
  }
  var detector = new BarcodeDetector({ formats: ['qr_code'] }), stream = null, running = false;
  function stop() { running = false; if (stream) stream.getTracks().forEach(function (t) { t.stop(); }); video.hidden = true; btn.textContent = 'Start camera'; }
  function loop() {
    if (!running) return;
    detector.detect(video).then(function (codes) {
      for (var i = 0; i < codes.length; i++) {
        try {
          var u = new URL(codes[i].rawValue);
          if (u.origin === location.origin && /^\/attend\/\d+\/\d{6}$/.test(u.pathname)) { stop(); location.href = u.pathname; return; }
        } catch (e) {}
      }
      setTimeout(loop, 250);
    }).catch(function () { setTimeout(loop, 400); });
  }
  btn.addEventListener('click', function () {
    if (running) { stop(); return; }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(function (s) {
      stream = s; video.srcObject = s; video.hidden = false; video.play(); running = true; btn.textContent = 'Stop camera';
      msg.textContent = 'Looking for the QR code...'; loop();
    }).catch(function () { msg.textContent = 'Camera permission was refused. Type the code instead.'; });
  });
})();
