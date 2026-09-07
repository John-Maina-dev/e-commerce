/* Reeves Boutique — storefront interactions */
(function () {
  'use strict';

  /* ---------- Theme ---------- */
  var colorPrefs = ['light', 'dark', 'system'];
  var systemMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function resolveDark(pref) {
    if (pref === 'dark') return true;
    if (pref === 'system' && systemMedia) return systemMedia.matches;
    return false;
  }

  function applyTheme(pref) {
    if (colorPrefs.indexOf(pref) === -1) pref = 'system';
    var dark = resolveDark(pref);
    var html = document.documentElement;
    html.setAttribute('data-theme-pref', pref);
    html.setAttribute('data-theme', dark ? 'dark' : 'light');
    html.style.colorScheme = dark ? 'dark' : 'light';
    try { localStorage.setItem('rb-theme', pref); } catch (e) { /* noop */ }
    document.querySelectorAll('#themeMenu [data-theme-choice]').forEach(function (btn) {
      if (btn.getAttribute('data-theme-choice') === pref) btn.setAttribute('data-active', '');
      else btn.removeAttribute('data-active');
    });
  }

  function storedTheme() {
    var stored = null;
    try { stored = localStorage.getItem('rb-theme'); } catch (e) { /* noop */ }
    return colorPrefs.indexOf(stored) === -1 ? 'system' : stored;
  }

  applyTheme(storedTheme());

  var themeToggle = document.getElementById('themeToggle');
  var themeMenu = document.getElementById('themeMenu');

  function closeThemeMenu() {
    if (!themeMenu) return;
    themeMenu.classList.remove('open');
    if (themeToggle) themeToggle.setAttribute('aria-expanded', 'false');
  }

  if (themeToggle && themeMenu) {
    themeToggle.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = themeMenu.classList.toggle('open');
      themeToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', function () { closeThemeMenu(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeThemeMenu();
    });
    themeMenu.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-theme-choice]');
      if (!btn) return;
      applyTheme(btn.getAttribute('data-theme-choice'));
      closeThemeMenu();
    });
  }

  if (systemMedia) {
    systemMedia.addEventListener('change', function () {
      applyTheme(storedTheme());
    });
  }

  /* ---------- Mobile nav ---------- */
  var navToggle = document.getElementById('navToggle');
  var siteNav = document.getElementById('siteNav');
  var manageSidebar = document.getElementById('manageSidebar');

  function closeNav() {
    if (siteNav) siteNav.classList.remove('open');
    if (manageSidebar) manageSidebar.classList.remove('open');
    if (navToggle) navToggle.setAttribute('aria-expanded', 'false');
  }

  if (navToggle) {
    navToggle.addEventListener('click', function () {
      var target = manageSidebar && manageSidebar.classList.contains('open')
        ? manageSidebar
        : (manageSidebar || siteNav);
      var isOpen = target.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });
  }

  /* ---------- Search suggestions ---------- */
  var searchForm = document.getElementById('searchForm');
  var searchInput = document.getElementById('searchInput');
  var searchClear = document.getElementById('searchClear');
  var suggestionsBox = document.getElementById('searchSuggestions');
  var suggestUrl = searchForm ? searchForm.getAttribute('data-suggest-url') : null;
  var debounceTimer = null;
  var activeIndex = -1;
  var suggestionItems = [];

  function hideSuggestions() {
    if (suggestionsBox) suggestionsBox.hidden = true;
    suggestionsBox.innerHTML = '';
    activeIndex = -1;
    suggestionItems = [];
  }

  function updateClear() {
    if (!searchClear || !searchInput) return;
    searchClear.hidden = !searchInput.value;
  }

  function renderSuggestions(data) {
    if (!suggestionsBox) return;
    suggestionItems = [];
    var items = data.results || [];
    items.forEach(function (p) {
      var li = document.createElement('a');
      li.href = '/products/' + p.slug + '/';
      li.className = 'suggestion-item';
      li.setAttribute('role', 'option');
      var img = p.image
        ? '<img src="' + p.image + '" alt="" loading="lazy">'
        : '<span class="suggestion-thumb">RB</span>';
      li.innerHTML = img +
        '<span class="suggestion-info"><span class="suggestion-name">' + p.name + '</span>' +
        '<span class="suggestion-sub">' + p.category +
        (p.out_of_stock ? ' · Out of stock' : '') + '</span></span>' +
        '<span class="suggestion-price">' + p.currency + ' ' + p.price + '</span>';
      suggestionItems.push(li);
      li.addEventListener('click', function () { hideSuggestions(); });
      suggestionsBox.appendChild(li);
    });
    if (searchInput && searchInput.value) {
      var all = document.createElement('a');
      all.href = '/products/?q=' + encodeURIComponent(searchInput.value.trim());
      all.className = 'suggestion-all';
      all.textContent = 'View all results for “' + searchInput.value.trim() + '”';
      all.addEventListener('click', function () { hideSuggestions(); });
      suggestionsBox.appendChild(all);
      suggestionItems.push(all);
    }
    suggestionsBox.hidden = items.length === 0 && suggestionItems.length === 0;
    activeIndex = -1;
  }

  function fetchSuggestions(term) {
    if (!suggestUrl || !suggestionsBox) return;
    if (term.length < 2) {
      hideSuggestions();
      return;
    }
    fetch(suggestUrl + '?q=' + encodeURIComponent(term))
      .then(function (resp) { return resp.json(); })
      .then(function (data) { renderSuggestions(data); })
      .catch(function () { hideSuggestions(); });
  }

  function setActive(index) {
    if (!suggestionItems.length) return;
    if (index < 0) index = suggestionItems.length - 1;
    if (index >= suggestionItems.length) index = 0;
    suggestionItems.forEach(function (el, i) {
      el.classList.toggle('active', i === index);
    });
    activeIndex = index;
    suggestionItems[index].scrollIntoView({ block: 'nearest' });
  }

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      updateClear();
      clearTimeout(debounceTimer);
      var term = searchInput.value.trim();
      if (term.length < 2) { hideSuggestions(); return; }
      debounceTimer = setTimeout(function () { fetchSuggestions(term); }, 200);
    });
    searchInput.addEventListener('keydown', function (e) {
      if (suggestionsBox && !suggestionsBox.hidden && suggestionItems.length) {
        if (e.key === 'ArrowDown') { e.preventDefault(); setActive(activeIndex + 1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIndex - 1); }
        else if (e.key === 'Enter' && activeIndex > -1) {
          e.preventDefault();
          suggestionItems[activeIndex].click();
        }
        else if (e.key === 'Escape') { e.preventDefault(); hideSuggestions(); }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        searchInput.value = '';
        updateClear();
        hideSuggestions();
      }
    });
    searchInput.addEventListener('blur', function () {
      setTimeout(function () { hideSuggestions(); }, 150);
    });
  }

  if (searchClear) {
    searchClear.addEventListener('click', function () {
      searchInput.value = '';
      searchInput.focus();
      updateClear();
      hideSuggestions();
    });
  }
  updateClear();

  /* ---------- Categories nav dropdown ---------- */
  document.querySelectorAll('.nav-dropdown').forEach(function (dd) {
    var btn = dd.querySelector('.nav-dropdown-btn');
    if (!btn) return;
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = dd.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    dd.addEventListener('mouseenter', function () {
      dd.classList.add('open');
      btn.setAttribute('aria-expanded', 'true');
    });
    dd.addEventListener('mouseleave', function () {
      dd.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    });
  });
  document.addEventListener('click', function () {
    document.querySelectorAll('.nav-dropdown.open').forEach(function (dd) {
      dd.classList.remove('open');
      var btn = dd.querySelector('.nav-dropdown-btn');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
  });

  /* ---------- Messages auto-dismiss ---------- */
  document.querySelectorAll('.message').forEach(function (el) {
    setTimeout(function () {
      el.style.transition = 'opacity .4s ease';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 400);
    }, 5000);
  });

  /* ---------- Product gallery ---------- */
  var thumbs = document.querySelectorAll('.gallery-thumbs button');
  thumbs.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var main = document.querySelector('.gallery-main img');
      var src = btn.getAttribute('data-src') || btn.querySelector('img').src;
      if (main) main.src = src;
      thumbs.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
    });
  });

  /* ---------- Quantity steppers ---------- */
  document.querySelectorAll('.qty-box').forEach(function (box) {
    var input = box.querySelector('input');
    var min = parseInt(input.getAttribute('min') || '1', 10) || 1;
    var max = parseInt(input.getAttribute('max') || '999', 10) || 999;
    var dec = box.querySelector('.qty-minus');
    var inc = box.querySelector('.qty-plus');
    if (dec) dec.addEventListener('click', function () {
      var v = parseInt(input.value, 10) || min;
      if (v > min) input.value = v - 1;
    });
    if (inc) inc.addEventListener('click', function () {
      var v = parseInt(input.value, 10) || min;
      if (v < max) input.value = v + 1;
    });
    input.addEventListener('change', function () {
      var v = parseInt(input.value, 10);
      if (isNaN(v) || v < min) input.value = min;
      if (v > max) input.value = max;
    });
  });

  /* ---------- Analytics bars ---------- */
  document.querySelectorAll('[data-chart]').forEach(function (chart) {
    var bars = chart.querySelectorAll('.bar[data-val]');
    if (!bars.length) return;
    var max = 0;
    bars.forEach(function (b) {
      var v = parseFloat(b.getAttribute('data-val')) || 0;
      if (v > max) max = v;
    });
    if (max <= 0) max = 1;
    bars.forEach(function (b) {
      var v = parseFloat(b.getAttribute('data-val')) || 0;
      b.style.height = (v / max * 100) + '%';
    });
  });

  /* ---------- Manage sidebar toggle ---------- */
  var manageToggle = document.getElementById('manageToggle');
  if (manageToggle && manageSidebar) {
    manageToggle.addEventListener('click', function () {
      var open = manageSidebar.classList.toggle('open');
      manageToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    manageSidebar.querySelectorAll('nav a').forEach(function (a) {
      a.addEventListener('click', function () { manageSidebar.classList.remove('open'); manageToggle.setAttribute('aria-expanded', 'false'); });
    });
  }

  /* ---------- Generic top-bar dropdowns ---------- */
  function bindDropdown(toggleId, menuId) {
    var toggle = document.getElementById(toggleId);
    var menu = document.getElementById(menuId);
    if (!toggle || !menu) return;
    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = menu.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', function (e) {
      if (!menu.contains(e.target) && !toggle.contains(e.target)) {
        menu.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        menu.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }
  bindDropdown('notifToggle', 'notifMenu');
  bindDropdown('profileToggle', 'profileMenu');

  /* ---------- Button loading states ---------- */
  document.querySelectorAll('form[data-submit-loading]').forEach(function (form) {
    form.addEventListener('submit', function () {
      var btn = form.querySelector('button[type="submit"]');
      if (!btn || btn.disabled) return;
      btn.classList.add('is-loading');
      btn.disabled = true;
      if (btn.dataset.loadingText && !btn.querySelector('svg')) btn.textContent = btn.dataset.loadingText;
    });
  });

  /* ---------- Modal component ---------- */
  function closeModal(backdrop) {
    backdrop.classList.remove('open');
    backdrop.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }
  document.querySelectorAll('[data-modal-open]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var backdrop = document.getElementById(btn.getAttribute('data-modal-open'));
      if (!backdrop) return;
      backdrop.classList.add('open');
      backdrop.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      var focusTarget = backdrop.querySelector('input, button');
      if (focusTarget) setTimeout(function () { focusTarget.focus(); }, 50);
    });
  });
  document.querySelectorAll('.modal-backdrop').forEach(function (backdrop) {
    backdrop.addEventListener('click', function (e) {
      if (e.target === backdrop || e.target.closest('[data-modal-close]')) closeModal(backdrop);
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-backdrop.open').forEach(closeModal);
    }
  });

  /* ---------- Image fade-in ---------- */
  document.querySelectorAll('img.lazy-img').forEach(function (img) {
    function loaded() { img.classList.add('is-loaded'); }
    if (img.complete) loaded();
    else { img.addEventListener('load', loaded); img.addEventListener('error', loaded); }
  });

  /* ---------- Message dismiss ---------- */
  document.querySelectorAll('.message-close').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var el = btn.closest('.message');
      if (!el) return;
      el.style.transition = 'opacity .25s ease';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 250);
    });
  });

  /* ---------- Product slider (touch/swipe + arrows + autoplay) ---------- */
  document.querySelectorAll('.slider').forEach(function (slider) {
    var track = slider.querySelector('.slider-track');
    if (!track) return;
    var prevBtn = slider.querySelector('.slider-nav.prev');
    var nextBtn = slider.querySelector('.slider-nav.next');

    function step() {
      var card = track.firstElementChild;
      if (!card) return 240;
      return card.getBoundingClientRect().width + parseFloat(getComputedStyle(track).gap || '16');
    }
    function scrollByDir(dir) {
      track.scrollBy({ left: dir * step(), behavior: 'smooth' });
    }
    function updateButtons() {
      var max = track.scrollWidth - track.clientWidth - 1;
      if (prevBtn) prevBtn.disabled = track.scrollLeft <= 0;
      if (nextBtn) nextBtn.disabled = track.scrollLeft >= max;
    }

    if (prevBtn) prevBtn.addEventListener('click', function () { scrollByDir(-1); pause(); });
    if (nextBtn) nextBtn.addEventListener('click', function () { scrollByDir(1); pause(); });
    track.addEventListener('scroll', updateButtons, { passive: true });
    window.addEventListener('resize', updateButtons);
    updateButtons();

    /* Keyboard support when the track is focused */
    track.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft') { e.preventDefault(); scrollByDir(-1); }
      if (e.key === 'ArrowRight') { e.preventDefault(); scrollByDir(1); }
    });

    /* Gentle autoplay; pauses on hover/touch and for reduced-motion users. */
    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduceMotion && nextBtn) {
      var timer = setInterval(function () {
        var max = track.scrollWidth - track.clientWidth - 1;
        if (track.scrollLeft >= max) {
          track.scrollTo({ left: 0, behavior: 'smooth' });
        } else {
          scrollByDir(1);
        }
      }, 5000);
      function pause() { clearInterval(timer); }
      slider.addEventListener('mouseenter', pause);
      slider.addEventListener('touchstart', pause, { passive: true });
    }
  });
})();
