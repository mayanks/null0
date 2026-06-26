document.addEventListener('DOMContentLoaded', function () {
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
