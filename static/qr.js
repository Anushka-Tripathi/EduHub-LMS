// Instructor QR screen: polls the server, swaps the QR image every time-step, shows live scans.
(function () {
  var app = document.getElementById('qr-app');
  if (!app) return;
  var $ = function (id) { return document.getElementById(id); };
  var lastStep = null, timer = null;
  function fmt(s) { s = Math.max(0, s | 0); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function row(r) {
    var tr = document.createElement('tr');
    [r.at, r.roll_number, r.name, r.status].forEach(function (v, i) {
      var td = document.createElement('td');
      if (i === 3) { var s = document.createElement('span'); s.className = 'chip ' + v; s.textContent = v; td.appendChild(s); }
      else td.textContent = v;
      tr.appendChild(td);
    });
    return tr;
  }
  function tick() {
    fetch(app.dataset.state, { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        $('qr-open').hidden = !s.open; $('qr-closed').hidden = s.open;
        var done = s.present + s.late;
        $('qr-count').textContent = done + ' scanned';
        $('qr-bar').style.width = (s.enrolled ? Math.round(100 * done / s.enrolled) : 0) + '%';
        $('qr-detail').textContent = 'present ' + s.present + ' · late ' + s.late + ' · of ' + s.enrolled + ' enrolled';
        var body = $('qr-recent'); body.innerHTML = '';
        if (!s.recent.length) body.innerHTML = '<tr><td colspan="4" class="empty">Nobody yet.</td></tr>';
        s.recent.forEach(function (r) { body.appendChild(row(r)); });
        if (s.open) {
          $('qr-code').textContent = s.code.slice(0, 3) + ' ' + s.code.slice(3);
          $('qr-next').textContent = s.next_in;
          $('qr-closes').textContent = fmt(s.closes_in);
          $('qr-late').textContent = s.late_in > 0 ? fmt(s.late_in) : 'now (late)';
          if (s.step_id !== lastStep) { lastStep = s.step_id; $('qr-img').src = app.dataset.img + '?s=' + s.step_id; }
        }
      })
      .catch(function () {});
  }
  tick(); timer = setInterval(tick, 2000);
})();
