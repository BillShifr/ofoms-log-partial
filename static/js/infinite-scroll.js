(function () {
  var activeObserver = null;

  function initInfiniteScroll() {
    if (activeObserver) {
      activeObserver.disconnect();
      activeObserver = null;
    }
    var controller = document.querySelector('[data-infinite-scroll]');
    var body = document.querySelector('[data-infinite-body]');
    var sentinel = controller && controller.querySelector('[data-infinite-sentinel]');
    var status = controller && controller.querySelector('[data-infinite-status]');
    var retry = controller && controller.querySelector('[data-infinite-retry]');
    var pagination = document.querySelector('[data-page-pagination]');

    if (!controller || !body || !sentinel || !status || !retry ||
        !('IntersectionObserver' in window)) return;

    var loading = false;
    var observer;

    function finishIfComplete() {
      if (controller.dataset.nextUrl) return false;
      observer.disconnect();
      sentinel.hidden = true;
      retry.hidden = true;
      status.textContent = 'Показаны все ' + controller.dataset.total;
      return true;
    }

    function loadNextPage() {
      if (loading || finishIfComplete()) return;
      loading = true;
      controller.setAttribute('aria-busy', 'true');
      retry.hidden = true;
      status.textContent = 'Загружаем следующие обращения…';

      fetch(controller.dataset.nextUrl, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      }).then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.text();
      }).then(function (html) {
        var documentPage = new DOMParser().parseFromString(html, 'text/html');
        var nextBody = documentPage.querySelector('[data-infinite-body]');
        var nextController = documentPage.querySelector('[data-infinite-scroll]');
        if (!nextBody || !nextController) throw new Error('Invalid journal page');

        var rows = Array.prototype.slice.call(nextBody.children);
        rows.forEach(function (row) { body.appendChild(document.importNode(row, true)); });
        controller.dataset.nextUrl = nextController.dataset.nextUrl || '';
        controller.dataset.loaded = nextController.dataset.loaded;
        status.textContent = 'Показано ' + controller.dataset.loaded + ' из ' +
          controller.dataset.total;

        var nextPagination = documentPage.querySelector('[data-page-pagination]');
        if (pagination && nextPagination) pagination.innerHTML = nextPagination.innerHTML;
        finishIfComplete();
      }).catch(function () {
        status.textContent = 'Не удалось загрузить следующую страницу.';
        retry.hidden = false;
      }).finally(function () {
        loading = false;
        controller.removeAttribute('aria-busy');
      });
    }

    retry.addEventListener('click', loadNextPage);
    observer = new IntersectionObserver(function (entries) {
      if (entries.some(function (entry) { return entry.isIntersecting; })) loadNextPage();
    }, { rootMargin: '320px 0px' });
    activeObserver = observer;
    observer.observe(sentinel);
    finishIfComplete();
  }

  document.addEventListener('DOMContentLoaded', initInfiniteScroll);
  document.addEventListener('portal:render', initInfiniteScroll);
})();
