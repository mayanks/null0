var SERVER_HOST = 'kuvera.mayanks.me';

document.addEventListener('DOMContentLoaded', function () {
  // Replace placeholder URLs — any element with data-server-url gets its
  // text content rewritten with the actual host.
  document.querySelectorAll('[data-server-url]').forEach(function (el) {
    var tpl = el.getAttribute('data-server-url');
    el.textContent = tpl.replace('SERVER_HOST', SERVER_HOST);
  });

  // Same for href/src attributes that reference the server.
  document.querySelectorAll('[data-server-href]').forEach(function (el) {
    var tpl = el.getAttribute('data-server-href');
    el.setAttribute('href', tpl.replace('SERVER_HOST', SERVER_HOST));
  });

  document.querySelectorAll('#setup-tabs .tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var tabId = btn.getAttribute('data-tab');

      document.querySelectorAll('#setup-tabs .tab-btn').forEach(function (t) {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');

      document.querySelectorAll('.tab-content').forEach(function (p) {
        p.classList.remove('active');
      });
      var target = document.getElementById('tab-' + tabId);
      if (target) target.classList.add('active');
    });
  });
});
