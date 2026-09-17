(function () {
  "use strict";

  var activeRequest = null;

  function sameDocumentUrl(url) {
    return url.origin === window.location.origin &&
      url.pathname === window.location.pathname &&
      url.search === window.location.search;
  }

  function bypassUrl(url) {
    return url.origin !== window.location.origin ||
      url.pathname.indexOf("/admin/") === 0 ||
      url.pathname.indexOf("/accounts/") === 0;
  }

  function restoreButton(button) {
    if (!button || !button.dataset.originalLabel) return;
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = button.dataset.originalLabel;
    delete button.dataset.originalLabel;
  }

  function currentUiState() {
    var activeTab = document.querySelector(".tab.is-active[data-tab]");
    return {
      scrollY: window.scrollY,
      activeTab: activeTab ? activeTab.dataset.tab : ""
    };
  }

  function restoreUiState(state, preserveScroll) {
    if (state.activeTab) {
      var tab = Array.prototype.find.call(document.querySelectorAll(".tab[data-tab]"), function (item) {
        return item.dataset.tab === state.activeTab;
      });
      if (tab) tab.click();
    }
    if (preserveScroll) window.scrollTo({ top: state.scrollY, behavior: "auto" });
    else window.scrollTo({ top: 0, behavior: "auto" });
  }

  function replacePage(html, url, options) {
    var parsed = new DOMParser().parseFromString(html, "text/html");
    var nextMain = parsed.querySelector("main#main-content");
    var currentMain = document.querySelector("main#main-content");
    if (!nextMain || !currentMain) throw new Error("partial navigation markup missing");

    var state = currentUiState();
    var nextNav = parsed.querySelector("nav.nav");
    var currentNav = document.querySelector("nav.nav");
    currentMain.replaceWith(document.importNode(nextMain, true));
    if (nextNav && currentNav) currentNav.replaceWith(document.importNode(nextNav, true));
    document.title = parsed.title || document.title;

    if (options.history === "push" && !sameDocumentUrl(url)) {
      history.pushState({ portal: true }, "", url.href);
    } else if (options.history === "replace") {
      history.replaceState({ portal: true }, "", url.href);
    }

    document.dispatchEvent(new CustomEvent("portal:render", {
      detail: { url: url.href }
    }));
    restoreUiState(state, Boolean(options.preserveScroll));
  }

  function requestPage(url, options) {
    options = options || {};
    var target = url instanceof URL ? url : new URL(url, window.location.href);
    if (bypassUrl(target)) {
      window.location.assign(target.href);
      return Promise.resolve(false);
    }

    if (activeRequest) activeRequest.abort();
    var controller = new AbortController();
    activeRequest = controller;
    var main = document.querySelector("main#main-content");
    if (main) main.setAttribute("aria-busy", "true");
    document.documentElement.classList.add("portal-loading");

    var fetchOptions = {
      method: options.method || "GET",
      body: options.body || null,
      credentials: "same-origin",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        "Accept": "text/html",
        "X-Requested-With": "XMLHttpRequest",
        "X-Portal-Navigation": "1"
      }
    };

    return fetch(target.href, fetchOptions).then(function (response) {
      var contentType = response.headers.get("content-type") || "";
      if (contentType.indexOf("text/html") === -1) {
        window.location.assign(target.href);
        return false;
      }
      return response.text().then(function (html) {
        var responseUrl = new URL(response.url || target.href, window.location.href);
        if (bypassUrl(responseUrl)) {
          window.location.assign(responseUrl.href);
          return false;
        }
        var preserve = options.preserveScroll;
        if (preserve === undefined) preserve = sameDocumentUrl(responseUrl);
        replacePage(html, responseUrl, {
          history: options.history || "push",
          preserveScroll: preserve
        });
        return true;
      });
    }).catch(function (error) {
      if (error.name === "AbortError") return false;
      if (window.showToast) {
        window.showToast("Не удалось обновить страницу. Повторите действие.", "danger");
      }
      throw error;
    }).finally(function () {
      if (activeRequest !== controller) return;
      activeRequest = null;
      var updatedMain = document.querySelector("main#main-content");
      if (updatedMain) updatedMain.removeAttribute("aria-busy");
      document.documentElement.classList.remove("portal-loading");
    });
  }

  window.portalNavigate = function (url, options) {
    return requestPage(url, options);
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("click", function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
          event.shiftKey || event.altKey) return;
      var link = event.target.closest("a[href]");
      if (!link || link.hasAttribute("download") || link.dataset.noAjax !== undefined ||
          (link.target && link.target !== "_self")) return;
      var href = link.getAttribute("href");
      if (!href || href.charAt(0) === "#" || href.indexOf("mailto:") === 0 ||
          href.indexOf("tel:") === 0 || href.indexOf("javascript:") === 0) return;
      var url = new URL(link.href, window.location.href);
      if (bypassUrl(url)) return;
      event.preventDefault();
      requestPage(url, { history: "push", preserveScroll: false }).catch(function () {
        window.location.assign(url.href);
      });
    });

    document.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      var form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      var formMethod = (form.getAttribute("method") || "get").toLowerCase();
      var formTarget = form.getAttribute("target") || "";
      if (formMethod === "dialog" ||
          form.dataset.noAjax !== undefined || (formTarget && formTarget !== "_self")) return;
      var url = new URL(form.getAttribute("action") || window.location.href, window.location.href);
      if (bypassUrl(url)) return;

      event.preventDefault();
      var submitter = event.submitter;
      var data = new FormData(form);
      if (submitter && submitter.name) data.set(submitter.name, submitter.value);
      var method = formMethod.toUpperCase();
      var body = null;
      if (method === "GET") {
        url.search = new URLSearchParams(data).toString();
      } else {
        body = data;
      }
      requestPage(url, {
        method: method,
        body: body,
        history: "push",
        preserveScroll: method !== "GET"
      }).catch(function () {
        restoreButton(submitter);
      });
    });
  });

  window.addEventListener("popstate", function () {
    requestPage(window.location.href, { history: "none", preserveScroll: false }).catch(function () {
      window.location.reload();
    });
  });
})();
