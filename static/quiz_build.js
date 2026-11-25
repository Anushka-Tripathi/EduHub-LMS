// Dynamic question blocks for the quiz builder.
(function () {
  var box = document.getElementById('questions'), add = document.getElementById('add-q');
  if (!box) return;
  var n = 0;
  function el(tag, attrs, text) { var e = document.createElement(tag); for (var k in (attrs || {})) e.setAttribute(k, attrs[k]); if (text) e.textContent = text; return e; }
  function addOption(wrap, i, j) {
    var line = el('div', { class: 'opt-edit' });
    line.appendChild(el('input', { type: 'radio', name: 'correct_' + i, value: j, title: 'correct answer' }));
    line.appendChild(el('input', { name: 'opt_' + i, placeholder: 'Option ' + (j + 1), maxlength: 300 }));
    wrap.appendChild(line);
  }
  function addQuestion() {
    var i = n++, card = el('div', { class: 'card question' });
    card.appendChild(el('h3', {}, 'Question ' + (i + 1)));
    var r = el('div', { class: 'row' });
    r.appendChild(el('input', { name: 'q_text', placeholder: 'Question text', maxlength: 1000 }));
    r.appendChild(el('input', { name: 'q_marks', type: 'number', value: 1, min: 0.5, step: 0.5, style: 'max-width:90px' }));
    card.appendChild(r);
    var opts = el('div', { class: 'opts' }); card.appendChild(opts);
    for (var j = 0; j < 4; j++) addOption(opts, i, j);
    box.appendChild(card);
  }
  add.addEventListener('click', addQuestion);
  addQuestion(); addQuestion();
})();
