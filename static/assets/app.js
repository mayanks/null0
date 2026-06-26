function switchTab(btn, tabId) {
  var tabs = document.querySelectorAll('#setup-tabs .tab-btn');
  tabs.forEach(function(t) {
    t.classList.remove('active');
    t.setAttribute('aria-selected', 'false');
  });
  btn.classList.add('active');
  btn.setAttribute('aria-selected', 'true');

  var panels = document.querySelectorAll('.tab-content');
  panels.forEach(function(p) { p.classList.remove('active'); });
  var target = document.getElementById('tab-' + tabId);
  if (target) target.classList.add('active');
}
