<<<<<<< HEAD
/* Point-of-Sale terminal.
   Supermarket-grade product register, hardware barcode scanner support,
   customer selection/registration, multi-tender split payments, live tax
   calculation, and multi-monitor customer display synchronization. */
=======
/* Point-of-Sale terminal. The browser only describes intent — every price,
   stock check and total is recomputed server-side at checkout. */
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
(function () {
  'use strict';

  var root = document.getElementById('posRoot');
  if (!root) return;

  var SEARCH_URL = root.dataset.searchUrl;
<<<<<<< HEAD
  var CATALOGUE_URL = root.dataset.catalogueUrl;
  var SCAN_URL = root.dataset.scanUrl;
  var RECOMMENDATIONS_URL = root.dataset.recommendationsUrl;
  var CUSTOMER_SEARCH_URL = root.dataset.customerSearchUrl;
  var CUSTOMER_CREATE_URL = root.dataset.customerCreateUrl;
  var CHECKOUT_URL = root.dataset.checkoutUrl;
  var STATE_URL_BASE = root.dataset.stateUrlBase;
  var CURRENCY = root.dataset.currency || 'KES';
  var STORE_NAME = root.dataset.storeName || 'Store';
  var CAN_DISCOUNT = root.dataset.canDiscount === '1';
  var TAX_ENABLED = root.dataset.taxEnabled === '1';
  var TAX_RATE = parseFloat(root.dataset.taxRate || '0');
=======
  var CHECKOUT_URL = root.dataset.checkoutUrl;
  var STATE_URL_BASE = root.dataset.stateUrlBase;
  var CURRENCY = root.dataset.currency || 'KES';
  var CAN_DISCOUNT = root.dataset.canDiscount === '1';
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  var CSRF = root.querySelector('[name=csrfmiddlewaretoken]').value;

  var searchInput = document.getElementById('posSearch');
  var resultsBox = document.getElementById('posResults');
<<<<<<< HEAD
  var grid = document.getElementById('posProductGrid');
  var gridEmpty = document.getElementById('posGridEmpty');
  var categoriesBox = document.getElementById('posCategories');
  var sortSelect = document.getElementById('posSortSelect');
  var recSection = document.getElementById('posRecommendationsSection');
  var recContainer = document.getElementById('posRecContainer');
  var cartBody = document.getElementById('posCartBody');
  var subtotalEl = document.getElementById('posSubtotal');
  var taxRow = document.getElementById('posTaxRow');
  var taxEl = document.getElementById('posTax');
  var totalEl = document.getElementById('posTotal');
  var discountEl = document.getElementById('posDiscount');
  var itemCountEl = document.getElementById('posItemCount');
  var payBtn = document.getElementById('posPayBtn');
  var clearBtn = document.getElementById('posClear');

  /* Customer selector elements */
  var customerBadge = document.getElementById('posCustomerBadge');
  var selectCustomerBtn = document.getElementById('posSelectCustomerBtn');
  var newCustomerBtn = document.getElementById('posNewCustomerBtn');
  var clearCustomerBtn = document.getElementById('posClearCustomerBtn');
  var customerSearchPopover = document.getElementById('customerSearchPopover');
  var custSearchInput = document.getElementById('custSearchInput');
  var custSearchResults = document.getElementById('custSearchResults');
  var newCustomerModal = document.getElementById('newCustomerModal');
  var newCustomerForm = document.getElementById('newCustomerForm');
  var newCustomerClose = document.getElementById('newCustomerClose');
  var newCustomerCancel = document.getElementById('newCustomerCancel');

  /* Customer state */
  var currentCustomer = { id: null, name: 'Walk-in customer', phone: '', email: '' };

  /* Customer-facing display (inline modal) */
  var customerDisplay = document.getElementById('customerDisplay');
  var cdTotal = document.getElementById('cdTotal');
  var cdHeadline = document.getElementById('cdHeadline');
  var cdStatus = document.getElementById('cdStatus');
  var cdMethod = document.getElementById('cdMethod');
  var cdItems = document.getElementById('cdItems');
  var cdItemCount = document.getElementById('cdItemCount');
  var displayOpen = false;

  /* Cart state: {id: {product, quantity}} */
  var cart = {};
  var catalogueTimer = null;
  var customerSearchTimer = null;
  var recTimer = null;
  var currentSort = '';
  var pendingSaleToken = null;
  var lastSaleSnapshot = null;
  var restoreOnClose = false;
  var currentCategory = '';
  var categoriesRendered = false;

  /* BroadcastChannel for multi-monitor / 2nd screen synchronization */
  var broadcastChannel = null;
  try {
    if ('BroadcastChannel' in window) {
      broadcastChannel = new BroadcastChannel('pos_display_channel');
    }
  } catch (e) {}

  function playScanBeep() {
    try {
      var AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      var ctx = new AudioContext();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.1);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.1);
    } catch (e) {}
  }

  function money(v) {
    return CURRENCY + ' ' + Number(v || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
=======
  var quickBox = document.getElementById('posQuick');
  var cartBody = document.getElementById('posCartBody');
  var subtotalEl = document.getElementById('posSubtotal');
  var totalEl = document.getElementById('posTotal');
  var discountEl = document.getElementById('posDiscount');
  var payBtn = document.getElementById('posPayBtn');
  var clearBtn = document.getElementById('posClear');

  /* cart: {id: {product, quantity}} */
  var cart = {};
  var searchTimer = null;

  function money(v) {
    return CURRENCY + ' ' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      credentials: 'same-origin',
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().then(function (data) { return { status: res.status, data: data }; });
    });
  }

  /* ------------------------------------------------------------------ */
<<<<<<< HEAD
  /* Multi-Screen Customer Display Sync                                  */
  /* ------------------------------------------------------------------ */

  function broadcastDisplay(status, extra) {
    extra = extra || {};
    var itemsArr = Object.keys(cart).map(function (id) {
      var it = cart[id];
      return {
        id: it.product.id,
        name: it.product.name,
        sku: it.product.sku,
        price: Number(it.product.price),
        quantity: it.quantity,
        line_total: lineTotal(it)
      };
    });

    var state = {
      status: status || (itemsArr.length ? 'active' : 'idle'),
      items: itemsArr,
      subtotal: cartSubtotal(),
      discount: discountValue(),
      tax: cartTax(),
      tax_rate: TAX_RATE,
      total: cartTotal(),
      customer: currentCustomer,
      change: extra.change || 0,
      method: extra.method || '',
      prompt_message: extra.prompt_message || '',
      order_number: extra.order_number || ''
    };

    // 1. Send to BroadcastChannel for zero-latency 2nd-screen update
    if (broadcastChannel) {
      try { broadcastChannel.postMessage(state); } catch (e) {}
    }

    // 2. Fallback to localStorage
    try {
      localStorage.setItem('pos_customer_state', JSON.stringify(state));
    } catch (e) {}

    // 3. Update inline customer modal if open
    if (displayOpen) renderCustomerDisplay();
  }

  /* ------------------------------------------------------------------ */
  /* Hardware Barcode Scanner & Search                                   */
  /* ------------------------------------------------------------------ */

  function scanBarcodeAndAdd(code, fallbackSearch) {
    code = (code || '').trim();
    if (!code) return;

    fetch(SCAN_URL + '?code=' + encodeURIComponent(code), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.ok && data.product) {
          if (data.product.out_of_stock) {
            flash(data.product.name + ' is out of stock.');
          } else {
            addToCart(data.product, 1);
            playScanBeep();
            flash('Scanned: ' + data.product.name);
          }
          searchInput.value = '';
          resultsBox.hidden = true;
        } else if (fallbackSearch) {
          fallbackSearch();
        } else {
          flash('Barcode not found: ' + code);
        }
      })
      .catch(function () {
        if (fallbackSearch) fallbackSearch();
      });
  }

  // Global listener for USB hardware barcode scanners typing rapid bursts
  var scanBuffer = '';
  var scanLastTime = 0;
  document.addEventListener('keydown', function (e) {
    var now = Date.now();
    var isInput = (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') && e.target !== searchInput;
    var interval = now - scanLastTime;
    scanLastTime = now;

    if (e.key === 'Enter') {
      if (scanBuffer.length >= 3 && interval < 60) {
        e.preventDefault();
        var scanned = scanBuffer;
        scanBuffer = '';
        scanBarcodeAndAdd(scanned);
        return;
      }
      scanBuffer = '';
    } else if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
      if (!isInput) {
        if (interval < 60) {
          scanBuffer += e.key;
        } else {
          scanBuffer = e.key;
        }
      }
    }
  });

  function resultRow(p) {
    var row = document.createElement('div');
    row.className = 'pos-result' + (p.out_of_stock ? ' is-out' : '');
    row.setAttribute('role', 'option');
    row.style.cssText = 'display:flex; align-items:center; gap:10px; padding:8px 12px; border-bottom:1px solid var(--border);';
    var img = p.image
      ? '<img src="' + escapeAttr(p.image) + '" alt="" style="width:42px; height:42px; object-fit:cover; border-radius:4px; flex-shrink:0;">'
      : '<span class="pos-result-ph" style="width:42px; height:42px; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.05); border-radius:4px; font-weight:700; flex-shrink:0;">' + escapeHtml((p.name || '?').charAt(0).toUpperCase()) + '</span>';

    var priceHtml = '';
    if (p.has_discount) {
      priceHtml = '<del class="muted small" style="margin-right:4px;">' + money(p.regular_price) + '</del>' +
                  '<b style="color:#059669;">' + money(p.price) + '</b> ' +
                  '<span style="background:#ecfdf5; color:#047857; font-size:10px; padding:1px 5px; border-radius:4px; font-weight:700;">-' + p.discount_percent + '%</span>';
    } else {
      priceHtml = '<b>' + money(p.price) + '</b>';
    }

    var stockBadge = p.out_of_stock
      ? '<span style="color:#ef4444; font-weight:700; font-size:11px;">Out of Stock</span>'
      : (p.low_stock
          ? '<span style="color:#f59e0b; font-weight:600; font-size:11px;">Low Stock (' + p.stock + ' left)</span>'
          : '<span class="muted" style="font-size:11px;">In Stock (' + p.stock + ')</span>');

    var details = [];
    if (p.sku) details.push('SKU: ' + p.sku);
    if (p.category) details.push(p.category);
    if (p.brand) details.push(p.brand);
    if (p.barcode) details.push('Barcode: ' + p.barcode);

    row.innerHTML =
      img +
      '<div style="flex:1; min-width:0;">' +
        '<div style="font-weight:600; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escapeHtml(p.name) + '</div>' +
        '<div class="muted" style="font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escapeHtml(details.join(' · ')) + '</div>' +
      '</div>' +
      '<div style="text-align:right; margin:0 8px; flex-shrink:0;">' +
        '<div>' + priceHtml + '</div>' +
        '<div>' + stockBadge + '</div>' +
      '</div>' +
      '<div style="flex-shrink:0;">' +
        (p.out_of_stock
          ? '<button type="button" class="btn btn-sm btn-ghost" disabled style="opacity:0.6; font-size:11px; padding:4px 8px;">Out</button>'
          : '<button type="button" class="btn btn-sm btn-primary pos-add-btn" style="padding:4px 10px; font-size:12px; font-weight:600;">+ Add</button>') +
      '</div>';

    if (!p.out_of_stock) {
      row.style.cursor = 'pointer';
      row.addEventListener('click', function () {
        addToCart(p);
        playScanBeep();
        flash('Added: ' + p.name);
        resultsBox.hidden = true;
        searchInput.value = '';
        searchInput.focus();
      });
=======
  /* Search                                                              */
  /* ------------------------------------------------------------------ */

  function renderResult(p) {
    var row = document.createElement('button');
    row.type = 'button';
    row.className = 'pos-result' + (p.out_of_stock ? ' is-out' : '');
    row.setAttribute('role', 'option');
    var img = p.image
      ? '<img src="' + p.image + '" alt="">'
      : '<span class="pos-result-ph">' + (p.name || '?').charAt(0).toUpperCase() + '</span>';
    row.innerHTML =
      img +
      '<span class="pos-result-name"><b>' + escapeHtml(p.name) + '</b>' +
      '<small>' + escapeHtml(p.sku || '') + (p.stock <= 5 && !p.out_of_stock ? ' · only ' + p.stock + ' left' : '') + '</small></span>' +
      '<span class="pos-result-meta"><b>' + money(p.price) + '</b>' +
      (p.out_of_stock ? '<small class="is-out">OUT OF STOCK</small>' : '<small>Stock: ' + p.stock + '</small>') +
      '</span>';
    if (!p.out_of_stock) {
      row.addEventListener('click', function () { addToCart(p); });
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    }
    return row;
  }

  function showResults(list) {
    resultsBox.innerHTML = '';
<<<<<<< HEAD
    list.forEach(function (p) { resultsBox.appendChild(resultRow(p)); });
    resultsBox.hidden = list.length === 0;
  }

  function renderCategories(categories) {
    if (categoriesRendered) return;
    categoriesRendered = true;
    categoriesBox.innerHTML = '';
    var all = document.createElement('button');
    all.type = 'button';
    all.className = 'pos-cat-chip is-active';
    all.dataset.category = '';
    all.textContent = 'All products';
    categoriesBox.appendChild(all);
    categories.forEach(function (c) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'pos-cat-chip';
      chip.dataset.category = c.slug;
      chip.textContent = c.name;
      categoriesBox.appendChild(chip);
    });
    categoriesBox.addEventListener('click', function (e) {
      var chip = e.target.closest('.pos-cat-chip');
      if (!chip) return;
      currentCategory = chip.dataset.category || '';
      categoriesBox.querySelectorAll('.pos-cat-chip').forEach(function (b) {
        b.classList.toggle('is-active', b === chip);
      });
      loadCatalogue();
    });
  }

  function productTile(p) {
    var tile = document.createElement('button');
    tile.type = 'button';
    tile.className = 'pos-tile' + (p.out_of_stock ? ' is-out' : '');
    tile.setAttribute('aria-label', 'Add ' + p.name);
    var media = p.image
      ? '<img src="' + escapeAttr(p.image) + '" alt="" loading="lazy">'
      : '<span class="pos-tile-ph">' + escapeHtml((p.name || '?').charAt(0).toUpperCase()) + '</span>';
    var stockClass = p.out_of_stock ? 'is-out' : (p.low_stock ? 'is-low' : '');
    var stockLabel = p.out_of_stock ? 'Out of stock' : (p.low_stock ? 'Only ' + p.stock + ' left' : p.stock + ' in stock');

    var priceHtml = '';
    if (p.has_discount) {
      priceHtml = '<del class="muted small" style="margin-right:2px; font-size:11px;">' + money(p.regular_price) + '</del> ' +
                  '<b style="color:#059669;">' + money(p.price) + '</b>';
    } else {
      priceHtml = '<b>' + money(p.price) + '</b>';
    }

    tile.innerHTML =
      '<span class="pos-tile-media">' + media +
        (p.out_of_stock ? '' : '<span class="pos-tile-add" aria-hidden="true">+</span>') +
        (p.has_discount ? '<span style="position:absolute; top:4px; left:4px; background:#10b981; color:#fff; font-size:10px; font-weight:700; padding:2px 5px; border-radius:4px;">-' + p.discount_percent + '%</span>' : '') +
      '</span>' +
      '<span class="pos-tile-body">' +
        '<span class="pos-tile-name">' + escapeHtml(p.name) + '</span>' +
        '<span class="pos-tile-sku">' + escapeHtml(p.sku || '') + (p.category ? ' · ' + escapeHtml(p.category) : '') + '</span>' +
        '<span class="pos-tile-foot">' + priceHtml +
        '<small class="pos-stock ' + stockClass + '">' + escapeHtml(stockLabel) + '</small></span>' +
      '</span>';
    if (!p.out_of_stock) {
      tile.addEventListener('click', function () {
        addToCart(p);
        playScanBeep();
        tile.classList.add('is-flash');
        setTimeout(function () { tile.classList.remove('is-flash'); }, 180);
      });
    }
    return tile;
  }

  function renderGrid(list) {
    grid.innerHTML = '';
    list.forEach(function (p) { grid.appendChild(productTile(p)); });
    grid.hidden = list.length === 0;
    gridEmpty.hidden = list.length !== 0;
  }

  function loadCatalogue() {
    var q = searchInput.value.trim();
    var url = CATALOGUE_URL + '?q=' + encodeURIComponent(q) +
              '&category=' + encodeURIComponent(currentCategory) +
              (currentSort ? '&sort=' + encodeURIComponent(currentSort) : '');
    return fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderCategories(data.categories || []);
        renderGrid(data.products || []);
      })
      .catch(function () {});
  }

  if (sortSelect) {
    sortSelect.addEventListener('change', function () {
      currentSort = sortSelect.value;
      loadCatalogue();
    });
  }

  function doSearch(q, autoAddSingle) {
    if (!q) return;
=======
    list.forEach(function (p) { resultsBox.appendChild(renderResult(p)); });
    resultsBox.hidden = list.length === 0;
    if (list.length) {
      quickBox.hidden = true;
    }
  }

  function doSearch(q, autoAddSingle) {
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    return fetch(SEARCH_URL + '?q=' + encodeURIComponent(q), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin'
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var results = data.results || [];
        if (autoAddSingle && results.length === 1 && !results[0].out_of_stock) {
          addToCart(results[0]);
<<<<<<< HEAD
          playScanBeep();
          searchInput.value = '';
          resultsBox.hidden = true;
          currentCategory = '';
          loadCatalogue();
          return;
        }
        if (autoAddSingle && results.length === 1 && results[0].out_of_stock) {
          flash(results[0].name + ' is out of stock.');
          return;
        }
        showResults(results);
      })
      .catch(function () {});
  }

  searchInput.addEventListener('input', function () {
    clearTimeout(catalogueTimer);
    resultsBox.hidden = true;
    catalogueTimer = setTimeout(function () { loadCatalogue(); }, 150);
=======
          searchInput.value = '';
          resultsBox.hidden = true;
          quickBox.hidden = false;
          return;
        }
        showResults(results);
        renderQuick(results);
      })
      .catch(function () { /* network hiccup; next keystroke retries */ });
  }

  function renderQuick(list) {
    quickBox.innerHTML = '';
    if (!list.length) {
      quickBox.innerHTML = '<p class="muted small">No products matched. Check the spelling or scan the barcode.</p>';
    }
    list.forEach(function (p) {
      var chip = renderResult(p);
      chip.classList.add('pos-chip');
      quickBox.appendChild(chip);
    });
    quickBox.hidden = false;
  }

  searchInput.addEventListener('input', function () {
    clearTimeout(searchTimer);
    var q = searchInput.value.trim();
    if (q.length < 2) { resultsBox.hidden = true; return; }
    searchTimer = setTimeout(function () { doSearch(q, false); }, 160);
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  });

  searchInput.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    var q = searchInput.value.trim();
    if (!q) return;
<<<<<<< HEAD
    // First try exact barcode/SKU scan endpoint, then fallback to general search
    scanBarcodeAndAdd(q, function () {
      doSearch(q, true);
    });
=======
    doSearch(q, true);
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  });

  document.addEventListener('click', function (e) {
    if (!resultsBox.contains(e.target) && e.target !== searchInput) resultsBox.hidden = true;
<<<<<<< HEAD
    if (customerSearchPopover && !customerSearchPopover.contains(e.target) && e.target !== selectCustomerBtn) {
      customerSearchPopover.hidden = true;
    }
  });

  document.getElementById('posSearchBtn').addEventListener('click', function () {
    var q = searchInput.value.trim();
    scanBarcodeAndAdd(q, function () {
      doSearch(q, true);
    });
    searchInput.focus();
  });

  /* ------------------------------------------------------------------ */
  /* Customer Selection & Quick-Registration                             */
  /* ------------------------------------------------------------------ */

  function setCustomer(cust) {
    currentCustomer = cust || { id: null, name: 'Walk-in customer', phone: '', email: '' };
    if (currentCustomer.name && currentCustomer.name !== 'Walk-in customer') {
      customerBadge.textContent = currentCustomer.name + (currentCustomer.phone ? ' (' + currentCustomer.phone + ')' : '');
      clearCustomerBtn.hidden = false;
      document.getElementById('customerName').value = currentCustomer.name;
      if (document.getElementById('mpesaPhone') && currentCustomer.phone) {
        document.getElementById('mpesaPhone').value = currentCustomer.phone;
      }
    } else {
      customerBadge.textContent = 'Walk-in customer';
      clearCustomerBtn.hidden = true;
      document.getElementById('customerName').value = '';
    }
    broadcastDisplay();
  }

  selectCustomerBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    customerSearchPopover.hidden = !customerSearchPopover.hidden;
    if (!customerSearchPopover.hidden) {
      custSearchInput.value = '';
      custSearchResults.innerHTML = '<span class="muted small">Type name or phone to search…</span>';
      custSearchInput.focus();
    }
  });

  clearCustomerBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    setCustomer(null);
  });

  custSearchInput.addEventListener('input', function () {
    clearTimeout(customerSearchTimer);
    var q = custSearchInput.value.trim();
    if (!q) {
      custSearchResults.innerHTML = '<span class="muted small">Type name or phone to search…</span>';
      return;
    }
    customerSearchTimer = setTimeout(function () {
      fetch(CUSTOMER_SEARCH_URL + '?q=' + encodeURIComponent(q), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin'
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          custSearchResults.innerHTML = '';
          var list = data.customers || [];
          if (!list.length) {
            custSearchResults.innerHTML = '<div class="muted small" style="padding: 6px 0;">No customer found. <a href="#" id="quickAddLink">Add new?</a></div>';
            var addLink = document.getElementById('quickAddLink');
            if (addLink) {
              addLink.addEventListener('click', function (ev) {
                ev.preventDefault();
                customerSearchPopover.hidden = true;
                openNewCustomerModal();
              });
            }
            return;
          }
          list.forEach(function (c) {
            var row = document.createElement('div');
            row.style.cssText = 'padding: 6px 8px; cursor: pointer; border-bottom: 1px solid var(--border);';
            row.innerHTML = '<b>' + escapeHtml(c.name) + '</b> ' +
              (c.phone ? '<small class="muted">' + escapeHtml(c.phone) + '</small>' : '') +
              (c.email ? '<small class="muted"> · ' + escapeHtml(c.email) + '</small>' : '');
            row.addEventListener('click', function () {
              setCustomer(c);
              customerSearchPopover.hidden = true;
            });
            custSearchResults.appendChild(row);
          });
        });
    }, 200);
  });

  function openNewCustomerModal() {
    newCustomerForm.reset();
    document.getElementById('newCustError').hidden = true;
    openModal(newCustomerModal);
    document.getElementById('newCustName').focus();
  }

  newCustomerBtn.addEventListener('click', openNewCustomerModal);
  newCustomerClose.addEventListener('click', function () { closeModal(newCustomerModal); });
  newCustomerCancel.addEventListener('click', function () { closeModal(newCustomerModal); });

  newCustomerForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var errEl = document.getElementById('newCustError');
    errEl.hidden = true;
    var name = document.getElementById('newCustName').value.trim();
    var phone = document.getElementById('newCustPhone').value.trim();
    var email = document.getElementById('newCustEmail').value.trim();

    postJSON(CUSTOMER_CREATE_URL, { name: name, phone: phone, email: email })
      .then(function (res) {
        if (!res.data.ok) {
          errEl.textContent = res.data.error || 'Failed to create customer.';
          errEl.hidden = false;
          return;
        }
        closeModal(newCustomerModal);
        setCustomer(res.data.customer);
        flash('Customer registered and selected: ' + res.data.customer.name);
      })
      .catch(function () {
        errEl.textContent = 'Network error. Please try again.';
        errEl.hidden = false;
      });
  });

  /* ------------------------------------------------------------------ */
  /* Cart & Tax Calculations                                             */
=======
  });
  document.getElementById('posSearchBtn').addEventListener('click', function () {
    doSearch(searchInput.value.trim(), true);
  });

  /* ------------------------------------------------------------------ */
  /* Cart                                                                */
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  /* ------------------------------------------------------------------ */

  function addToCart(p, qty) {
    qty = qty || 1;
    var entry = cart[p.id];
    if (!entry) {
      entry = cart[p.id] = { product: p, quantity: 0 };
    }
    if (entry.quantity + qty > p.stock) {
      flash('Only ' + p.stock + ' unit(s) of ' + p.name + ' in stock.');
      entry.quantity = p.stock;
    } else {
      entry.quantity += qty;
    }
<<<<<<< HEAD
    endSaleAttempt();
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    renderCart();
  }

  function setQty(id, qty) {
    var entry = cart[id];
    if (!entry) return;
    qty = Math.max(0, Math.min(qty, entry.product.stock));
    if (qty === 0) { delete cart[id]; } else { entry.quantity = qty; }
<<<<<<< HEAD
    endSaleAttempt();
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    renderCart();
  }

  function lineTotal(entry) {
    return Number(entry.product.price) * entry.quantity;
  }

  function cartSubtotal() {
    return Object.keys(cart).reduce(function (sum, id) { return sum + lineTotal(cart[id]); }, 0);
  }

<<<<<<< HEAD
  function cartQuantity() {
    return Object.keys(cart).reduce(function (sum, id) { return sum + cart[id].quantity; }, 0);
  }

=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  function discountValue() {
    var d = CAN_DISCOUNT && discountEl ? parseFloat(discountEl.value || '0') : 0;
    return isFinite(d) && d > 0 ? Math.min(d, cartSubtotal()) : 0;
  }

<<<<<<< HEAD
  function cartTax() {
    if (!TAX_ENABLED) return 0;
    var taxable = Math.max(0, cartSubtotal() - discountValue());
    return Math.round(taxable * TAX_RATE) / 100;
  }

  function cartTotal() {
    var sub = cartSubtotal();
    var disc = discountValue();
    var taxable = Math.max(0, sub - disc);
    var tax = cartTax();
    return Math.round((taxable + tax) * 100) / 100;
  }

=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  function renderCart() {
    var ids = Object.keys(cart);
    cartBody.innerHTML = '';
    if (!ids.length) {
<<<<<<< HEAD
      cartBody.innerHTML =
        '<div class="pos-ticket-empty">' +
        '<svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h12l-1.5 4H7.5L6 2z"/><path d="M5 6h14l-1 14H6L5 6z"/><path d="M9 10h6M9 14h6"/></svg>' +
        '<p>No items yet.<br><span class="muted">Scan a barcode or tap a product.</span></p></div>';
    }
    ids.forEach(function (id) {
      var e = cart[id];
      var line = document.createElement('div');
      line.className = 'pos-line';
      line.innerHTML =
        '<div class="pos-line-main">' +
          '<b>' + escapeHtml(e.product.name) + '</b>' +
          '<small>' + escapeHtml(e.product.sku || '') + (e.product.barcode ? ' · ' + e.product.barcode : '') + ' · ' + money(e.product.price) + ' each</small>' +
        '</div>' +
        '<div class="pos-line-qty">' +
          '<div class="qty-stepper">' +
            '<button type="button" data-step="-1" aria-label="Decrease">\u2212</button>' +
            '<input type="number" min="1" max="' + e.product.stock + '" value="' + e.quantity + '" aria-label="Quantity">' +
            '<button type="button" data-step="1" aria-label="Increase">+</button>' +
          '</div>' +
        '</div>' +
        '<div class="pos-line-total"><b>' + money(lineTotal(e)) + '</b>' +
          '<button type="button" class="pos-remove" aria-label="Remove">\u00d7</button></div>';
      line.querySelector('[data-step="-1"]').addEventListener('click', function () { setQty(id, e.quantity - 1); });
      line.querySelector('[data-step="1"]').addEventListener('click', function () { setQty(id, e.quantity + 1); });
      line.querySelector('input').addEventListener('change', function (ev) {
        setQty(id, parseInt(ev.target.value || '0', 10));
      });
      line.querySelector('.pos-remove').addEventListener('click', function () { setQty(id, 0); });
      cartBody.appendChild(line);
    });

    var sub = cartSubtotal();
    subtotalEl.textContent = money(sub);

    var tax = cartTax();
    if (taxRow) {
      if (TAX_ENABLED && tax > 0) {
        taxRow.hidden = false;
        taxEl.textContent = money(tax);
      } else {
        taxRow.hidden = true;
      }
    }

    var total = cartTotal();
    totalEl.textContent = money(total);
    itemCountEl.textContent = cartQuantity() + (cartQuantity() === 1 ? ' item' : ' items');
    payBtn.disabled = !ids.length;
    clearBtn.disabled = !ids.length;
    payBtn.textContent = ids.length ? 'Charge ' + money(total) + ' (F4)' : 'Charge (F4)';

    broadcastDisplay();
    fetchAndRenderRecommendations();
  }

  /* ------------------------------------------------------------------ */
  /* POS Cross-Selling & Recommendations ("YOU MAY ALSO LIKE")         */
  /* ------------------------------------------------------------------ */

  function fetchAndRenderRecommendations() {
    if (!recSection || !recContainer || !RECOMMENDATIONS_URL) return;
    var ids = Object.keys(cart);
    if (!ids.length) {
      recSection.hidden = true;
      recContainer.innerHTML = '';
      return;
    }

    clearTimeout(recTimer);
    recTimer = setTimeout(function () {
      fetch(RECOMMENDATIONS_URL + '?items=' + encodeURIComponent(ids.join(',')), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin'
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.ok || !data.recommendations) {
            recSection.hidden = true;
            return;
          }
          var recs = data.recommendations;
          var items = recs.all || [];
          if (!items.length) {
            recSection.hidden = true;
            return;
          }

          recContainer.innerHTML = '';
          items.forEach(function (p) {
            var card = document.createElement('div');
            card.className = 'pos-rec-card';
            card.style.cssText = 'flex: 0 0 145px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 8px; display: flex; flex-direction: column; justify-content: space-between; gap: 6px; position: relative; font-size: 11px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;';

            var media = p.image
              ? '<img src="' + escapeAttr(p.image) + '" style="width: 100%; height: 60px; object-fit: cover; border-radius: 4px; display: block;">'
              : '<div style="width: 100%; height: 60px; background: rgba(0,0,0,0.04); border-radius: 4px; display: flex; align-items: center; justify-content: center; font-weight: 700; color: var(--muted); font-size: 16px;">' + escapeHtml((p.name || '?').charAt(0).toUpperCase()) + '</div>';

            var priceHtml = p.has_discount
              ? '<span style="color:#059669; font-weight:700;">' + money(p.price) + '</span>'
              : '<span style="font-weight:700;">' + money(p.price) + '</span>';

            card.innerHTML =
              '<div>' +
                media +
                '<div style="font-weight: 600; margin-top: 5px; line-height: 1.2; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; min-height: 26px;" title="' + escapeAttr(p.name) + '">' + escapeHtml(p.name) + '</div>' +
              '</div>' +
              '<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">' +
                priceHtml +
                '<button type="button" class="btn btn-sm" style="padding: 2px 7px; font-size: 10px; font-weight: 700;">+ Add</button>' +
              '</div>';

            card.addEventListener('click', function () {
              addToCart(p, 1);
              playScanBeep();
              flash('Cross-sell added: ' + p.name);
            });

            recContainer.appendChild(card);
          });

          recSection.hidden = false;
        })
        .catch(function () {
          recSection.hidden = true;
        });
    }, 150);
  }

  discountEl.addEventListener('input', function () {
    endSaleAttempt();
    renderCart();
  });

  clearBtn.addEventListener('click', function () {
    if (!Object.keys(cart).length) return;
    if (!window.confirm('Are you sure you want to clear all items from this sale?')) return;
    cart = {};
    discountEl.value = '0';
    endSaleAttempt();
=======
      cartBody.innerHTML = '<tr class="pos-empty"><td colspan="5" class="muted">No items yet. Search or scan to begin.</td></tr>';
    }
    ids.forEach(function (id) {
      var e = cart[id];
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td><b>' + escapeHtml(e.product.name) + '</b><small class="muted">' + escapeHtml(e.product.sku || '') + '</small></td>' +
        '<td><div class="qty-stepper">' +
        '<button type="button" data-step="-1" aria-label="Decrease">\u2212</button>' +
        '<input type="number" min="1" max="' + e.product.stock + '" value="' + e.quantity + '" aria-label="Quantity">' +
        '<button type="button" data-step="1" aria-label="Increase">+</button></div></td>' +
        '<td>' + money(e.product.price) + '</td>' +
        '<td><b>' + money(lineTotal(e)) + '</b></td>' +
        '<td><button type="button" class="pos-remove" aria-label="Remove">\u00d7</button></td>';
      tr.querySelector('[data-step="-1"]').addEventListener('click', function () { setQty(id, e.quantity - 1); });
      tr.querySelector('[data-step="1"]').addEventListener('click', function () { setQty(id, e.quantity + 1); });
      tr.querySelector('input').addEventListener('change', function (ev) {
        setQty(id, parseInt(ev.target.value || '0', 10));
      });
      tr.querySelector('.pos-remove').addEventListener('click', function () { setQty(id, 0); });
      cartBody.appendChild(tr);
    });
    var sub = cartSubtotal();
    subtotalEl.textContent = money(sub);
    totalEl.textContent = money(sub - discountValue());
    payBtn.disabled = !ids.length;
    clearBtn.disabled = !ids.length;
  }

  discountEl.addEventListener('input', renderCart);

  clearBtn.addEventListener('click', function () {
    if (!Object.keys(cart).length) return;
    cart = {};
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    renderCart();
  });

  /* ------------------------------------------------------------------ */
<<<<<<< HEAD
  /* Inline Customer Display modal                                       */
  /* ------------------------------------------------------------------ */

  function openCustomerDisplay() {
    displayOpen = true;
    customerDisplay.hidden = false;
    document.body.classList.add('cd-open');
    renderCustomerDisplay();
  }

  function closeCustomerDisplay() {
    displayOpen = false;
    customerDisplay.hidden = true;
    document.body.classList.remove('cd-open');
    searchInput.focus();
  }

  function setCdStatus(text, tone) {
    cdStatus.textContent = text;
    cdStatus.className = 'cd-status' + (tone ? ' is-' + tone : '');
  }

  function renderCustomerDisplay() {
    if (!customerDisplay) return;
    var ids = Object.keys(cart);
    var total = cartTotal();
    cdTotal.textContent = money(total);
    cdItemCount.textContent = cartQuantity() + (cartQuantity() === 1 ? ' item' : ' items') + ' in this sale';
    cdHeadline.textContent = ids.length ? 'Please pay' : 'Welcome';
    if (!ids.length) {
      setCdStatus('Your cashier will take payment shortly.', '');
      cdMethod.textContent = 'Ready when you are';
    }
    cdItems.innerHTML = '';
    ids.forEach(function (id) {
      var e = cart[id];
      var row = document.createElement('div');
      row.className = 'cd-item';
      row.innerHTML =
        '<span class="cd-item-qty">' + e.quantity + '×</span>' +
        '<span class="cd-item-name">' + escapeHtml(e.product.name) + '</span>' +
        '<b>' + money(lineTotal(e)) + '</b>';
      cdItems.appendChild(row);
    });
    if (!ids.length) {
      cdItems.innerHTML = '<div class="cd-item cd-item-empty">Your basket is empty.</div>';
    }
  }

  document.getElementById('posCustomerBtn').addEventListener('click', function () {
    if (displayOpen) { closeCustomerDisplay(); } else { openCustomerDisplay(); }
  });
  document.getElementById('posCustomerPrompt').addEventListener('click', function () {
    openCustomerDisplay();
    if (Object.keys(cart).length) {
      setCdStatus('Please pay ' + money(cartTotal()) + '.', 'prompt');
      cdMethod.textContent = 'Amount due';
      broadcastDisplay('paying', { prompt_message: 'Amount due: ' + money(cartTotal()) });
    }
  });
  document.getElementById('cdClose').addEventListener('click', closeCustomerDisplay);

  /* ------------------------------------------------------------------ */
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  /* Printer preference                                                  */
  /* ------------------------------------------------------------------ */

  function getPrinterSize() {
    return localStorage.getItem('pos_printer_size') || '80';
  }

  var printerBtns = document.querySelectorAll('.pos-printer-size');
  printerBtns.forEach(function (btn) {
    if (btn.dataset.size === getPrinterSize()) btn.classList.add('is-active');
    btn.addEventListener('click', function () {
      localStorage.setItem('pos_printer_size', btn.dataset.size);
      printerBtns.forEach(function (b) { b.classList.toggle('is-active', b === btn); });
    });
  });

  /* ------------------------------------------------------------------ */
<<<<<<< HEAD
  /* Payment Modal & Split Tenders                                       */
=======
  /* Payment                                                             */
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  /* ------------------------------------------------------------------ */

  var modal = document.getElementById('payModal');
  var payMethod = 'cash';
  var busy = false;
<<<<<<< HEAD
  var splitTendersContainer = document.getElementById('splitTendersContainer');
  var addSplitTenderBtn = document.getElementById('addSplitTenderBtn');
  var splitRemainingEl = document.getElementById('splitRemaining');

  payBtn.addEventListener('click', function () {
    if (!Object.keys(cart).length) return;
    var total = cartTotal();
    document.getElementById('payTotalLabel').textContent = money(total);
    document.getElementById('cashReceived').value = total.toFixed(2);
    renderQuickCash(total);
    updateChange();
    initSplitTenders(total);
    openModal(modal);
    selectMethod('cash');

    broadcastDisplay('paying', {
      method: 'CASH',
      prompt_message: 'Please hand ' + money(total) + ' to the cashier.'
    });
=======

  payBtn.addEventListener('click', function () {
    if (!Object.keys(cart).length) return;
    document.getElementById('payTotalLabel').textContent = money(cartSubtotal() - discountValue());
    document.getElementById('cashReceived').value = (cartSubtotal() - discountValue()).toFixed(2);
    updateChange();
    openModal(modal);
    selectMethod('cash');
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  });

  document.querySelectorAll('.pay-method').forEach(function (btn) {
    btn.addEventListener('click', function () { selectMethod(btn.dataset.method); });
  });

  function selectMethod(m) {
    payMethod = m;
    document.querySelectorAll('.pay-method').forEach(function (b) {
      b.classList.toggle('is-active', b.dataset.method === m);
    });
    document.querySelectorAll('.pay-body[data-panel]').forEach(function (p) {
      p.hidden = p.dataset.panel !== m;
    });
<<<<<<< HEAD

    var total = cartTotal();
    var msg = 'Please pay ' + money(total) + ' to the cashier.';
    if (m === 'cash') msg = 'Please hand ' + money(total) + ' to the cashier.';
    else if (m === 'mpesa') msg = 'Check your phone — enter your M-Pesa PIN to approve ' + money(total) + '.';
    else if (m === 'card') msg = 'Please tap or insert your card on the terminal for ' + money(total) + '.';
    else if (m === 'bank') msg = 'Please complete the bank transfer for ' + money(total) + '.';
    else if (m === 'split') msg = 'Multi-tender payment in progress.';

    broadcastDisplay('paying', { method: m.toUpperCase(), prompt_message: msg });
    hideError();
  }

  function renderQuickCash(total) {
    var box = document.getElementById('payQuickCash');
    if (!box) return;
    var values = [
      total,
      Math.ceil(total / 50) * 50,
      Math.ceil(total / 100) * 100,
      Math.ceil(total / 500) * 500,
      Math.ceil(total / 1000) * 1000,
      total + 1000,
      total + 2000
    ];
    var seen = {};
    var unique = [];
    values.forEach(function (v) {
      v = Math.round(v * 100) / 100;
      if (v < total || seen[v]) return;
      seen[v] = true;
      unique.push(v);
    });
    unique.sort(function (a, b) { return a - b; });
    box.innerHTML = '<span class="muted small">Quick cash presets</span><div class="pos-cash-btns"></div>';
    var btns = box.querySelector('.pos-cash-btns');
    unique.slice(0, 6).forEach(function (v, i) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pos-cash-btn' + (i === 0 ? ' is-exact' : '');
      b.textContent = i === 0 ? 'Exact · ' + money(v) : money(v);
      b.addEventListener('click', function () {
        document.getElementById('cashReceived').value = v.toFixed(2);
        updateChange();
      });
      btns.appendChild(b);
    });
  }

  function updateChange() {
    var received = parseFloat(document.getElementById('cashReceived').value || '0');
    var total = cartTotal();
    var change = Math.max(0, received - total);
    document.getElementById('changeDue').textContent = money(change);
    document.getElementById('cashError').hidden = !(received < total);

    if (payMethod === 'cash') {
      broadcastDisplay('paying', {
        method: 'CASH',
        change: change,
        prompt_message: change > 0 ? 'Change due: ' + money(change) : 'Amount due: ' + money(total)
      });
    }
  }
  document.getElementById('cashReceived').addEventListener('input', updateChange);

  /* Split Tenders Builder */
  function initSplitTenders(total) {
    var half1 = Math.floor(total / 2);
    var half2 = total - half1;
    splitTendersContainer.innerHTML = '';
    addSplitRow('cash', half1);
    addSplitRow('mpesa', half2);
    updateSplitRemaining();
  }

  function addSplitRow(defaultMethod, defaultAmount) {
    var row = document.createElement('div');
    row.className = 'split-tender-row';
    row.style.cssText = 'background: rgba(0,0,0,0.02); border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-bottom: 10px; position: relative;';
    row.innerHTML =
      '<div style="display: grid; grid-template-columns: 120px 1fr 30px; gap: 8px; margin-bottom: 6px; align-items: center;">' +
        '<select class="form-control split-method-select" style="font-weight: 600;">' +
          '<option value="cash"' + (defaultMethod === 'cash' ? ' selected' : '') + '>Cash</option>' +
          '<option value="mpesa"' + (defaultMethod === 'mpesa' ? ' selected' : '') + '>M-Pesa</option>' +
          '<option value="card"' + (defaultMethod === 'card' ? ' selected' : '') + '>Card</option>' +
          '<option value="bank"' + (defaultMethod === 'bank' ? ' selected' : '') + '>Bank</option>' +
        '</select>' +
        '<input type="number" class="form-control split-amount-input" step="0.01" min="0" value="' + (defaultAmount ? defaultAmount.toFixed(2) : '') + '" placeholder="Amount (' + CURRENCY + ')">' +
        '<button type="button" class="btn btn-ghost btn-sm remove-split-row" style="padding: 4px; color: #ef4444;" title="Remove tender">×</button>' +
      '</div>' +
      '<div class="split-tender-extra"></div>';

    var methodSelect = row.querySelector('.split-method-select');
    var extraBox = row.querySelector('.split-tender-extra');
    var amtInput = row.querySelector('.split-amount-input');
    var removeBtn = row.querySelector('.remove-split-row');

    function renderExtra() {
      var m = methodSelect.value;
      if (m === 'cash') {
        extraBox.innerHTML = '<input type="number" class="form-control split-cash-rec" step="0.01" min="0" placeholder="Cash received (optional for change)">';
      } else if (m === 'mpesa') {
        extraBox.innerHTML = '<input type="tel" class="form-control split-mpesa-phone" value="' + escapeAttr(currentCustomer.phone || '') + '" placeholder="Customer phone (07XX XXX XXX)">';
      } else if (m === 'card') {
        extraBox.innerHTML = '<input type="text" class="form-control split-card-ref" placeholder="Card terminal auth / ref (optional)">';
      } else if (m === 'bank') {
        extraBox.innerHTML = '<input type="text" class="form-control split-bank-ref" placeholder="Bank transfer reference (optional)">';
      }
    }
    renderExtra();

    methodSelect.addEventListener('change', renderExtra);
    amtInput.addEventListener('input', updateSplitRemaining);
    removeBtn.addEventListener('click', function () {
      if (splitTendersContainer.querySelectorAll('.split-tender-row').length <= 2) {
        flash('Split payment requires at least two tenders.');
        return;
      }
      row.remove();
      updateSplitRemaining();
    });

    splitTendersContainer.appendChild(row);
  }

  addSplitTenderBtn.addEventListener('click', function () {
    var rem = calculateSplitRemaining();
    addSplitRow('cash', rem > 0 ? rem : 0);
    updateSplitRemaining();
  });

  function calculateSplitRemaining() {
    var allocated = 0;
    splitTendersContainer.querySelectorAll('.split-amount-input').forEach(function (inp) {
      allocated += parseFloat(inp.value || '0');
    });
    return Math.round((cartTotal() - allocated) * 100) / 100;
  }

  function updateSplitRemaining() {
    var rem = calculateSplitRemaining();
    if (Math.abs(rem) < 0.005) {
      splitRemainingEl.textContent = 'Allocated in full (0.00)';
      splitRemainingEl.style.color = '#10b981';
    } else if (rem > 0) {
      splitRemainingEl.textContent = money(rem) + ' remaining';
      splitRemainingEl.style.color = '#ef4444';
    } else {
      splitRemainingEl.textContent = money(Math.abs(rem)) + ' over allocated';
      splitRemainingEl.style.color = '#ef4444';
    }
  }

=======
    hideError();
  }

  function updateChange() {
    var received = parseFloat(document.getElementById('cashReceived').value || '0');
    var total = cartSubtotal() - discountValue();
    var change = received - total;
    document.getElementById('changeDue').textContent = money(Math.max(0, change));
    document.getElementById('cashError').hidden = !(received < total);
  }
  document.getElementById('cashReceived').addEventListener('input', updateChange);

>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  document.getElementById('payClose').addEventListener('click', function () { closeModal(modal); });
  modal.addEventListener('click', function (e) { if (e.target === modal) closeModal(modal); });

  document.getElementById('payConfirm').addEventListener('click', function () {
    if (busy) return;
    hideError();

<<<<<<< HEAD
    var total = cartTotal();
    var received = null;

    if (payMethod === 'cash') {
      received = parseFloat(document.getElementById('cashReceived').value || '0');
      if (received < total) {
        showError('Cash received is less than the total due.');
=======
    if (payMethod === 'cash') {
      var received = parseFloat(document.getElementById('cashReceived').value || '0');
      if (received < cartSubtotal() - discountValue()) {
        showError('Cash received is less than the total.');
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        return;
      }
    }

<<<<<<< HEAD
    var items = Object.keys(cart).map(function (id) {
      return { id: Number(id), quantity: cart[id].quantity };
    });

=======
    busy = true;
    this.disabled = true;

    var items = Object.keys(cart).map(function (id) {
      return { id: Number(id), quantity: cart[id].quantity };
    });
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    var body = {
      items: items,
      payment_method: payMethod,
      discount: CAN_DISCOUNT ? discountValue() : 0,
      token: saleToken(),
<<<<<<< HEAD
      customer_id: currentCustomer.id,
      customer_name: currentCustomer.name || document.getElementById('customerName').value || ''
    };

    if (payMethod === 'cash') {
      body.cash_received = received;
    } else if (payMethod === 'mpesa') {
      body.phone = document.getElementById('mpesaPhone').value.trim();
      if (!body.phone) { showError('Enter the customer phone number for M-Pesa.'); return; }
    } else if (payMethod === 'card') {
      body.card_reference = document.getElementById('cardReference').value.trim();
    } else if (payMethod === 'bank') {
      body.bank_reference = document.getElementById('bankReference').value.trim();
    } else if (payMethod === 'split') {
      var rem = calculateSplitRemaining();
      if (Math.abs(rem) >= 0.01) {
        showError('The sum of all split tenders must equal the grand total (' + money(total) + '). Remaining: ' + money(rem));
        return;
      }
      var tenders = [];
      var hasError = false;
      splitTendersContainer.querySelectorAll('.split-tender-row').forEach(function (row) {
        var m = row.querySelector('.split-method-select').value;
        var amt = parseFloat(row.querySelector('.split-amount-input').value || '0');
        if (amt <= 0) {
          hasError = true;
          showError('Every split tender must have an amount greater than zero.');
          return;
        }
        var item = { method: m, amount: amt };
        if (m === 'cash') {
          var recInp = row.querySelector('.split-cash-rec');
          item.cash_received = recInp && recInp.value ? parseFloat(recInp.value) : amt;
        } else if (m === 'mpesa') {
          var phInp = row.querySelector('.split-mpesa-phone');
          item.phone = phInp ? phInp.value.trim() : '';
          if (!item.phone) {
            hasError = true;
            showError('Phone number is required for the M-Pesa portion of the split.');
            return;
          }
        } else if (m === 'card') {
          var cInp = row.querySelector('.split-card-ref');
          item.reference = cInp ? cInp.value.trim() : '';
        } else if (m === 'bank') {
          var bInp = row.querySelector('.split-bank-ref');
          item.reference = bInp ? bInp.value.trim() : '';
        }
        tenders.push(item);
      });
      if (hasError) return;
      body.tenders = tenders;
    }

    lastSaleSnapshot = snapshotCart();
    busy = true;
    this.disabled = true;
    var origText = this.textContent;
    this.textContent = 'Processing sale…';

    var self = this;
    function finish() {
      busy = false;
      self.disabled = false;
      self.textContent = origText;
    }

    postJSON(CHECKOUT_URL, body).then(function (r) {
      finish();
      if (!r.data.ok) {
        if (r.status === 403) { closeModal(modal); flash(r.data.error || 'Not authorized.'); return; }
=======
      customer_name: document.getElementById('customerName').value || ''
    };
    if (payMethod === 'cash') body.cash_received = received;
    if (payMethod === 'mpesa') {
      body.phone = document.getElementById('mpesaPhone').value.trim();
      if (!body.phone) { showError('Enter the customer phone number.'); busy = false; this.disabled = false; return; }
    }
    if (payMethod === 'other') {
      body.customer_name = body.customer_name || document.getElementById('otherName').value || '';
    }

    postJSON(CHECKOUT_URL, body).then(function (r) {
      busy = false;
      payConfirmBtn().disabled = false;
      if (!r.data.ok) {
        if (r.status === 403) { closeModal(modal); flash(r.data.error || 'Not allowed.'); return; }
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        showError(r.data.error || 'The sale could not be completed.');
        return;
      }
      closeModal(modal);
      handleSaleResult(r.data.sale);
    }).catch(function () {
<<<<<<< HEAD
      finish();
      showError('Network problem — the sale may or may not be recorded. Press Complete again to retry safely.');
    });
  });

  function snapshotCart() {
    var copy = {};
    Object.keys(cart).forEach(function (id) {
      copy[id] = { product: cart[id].product, quantity: cart[id].quantity };
    });
    return { cart: copy, discount: discountEl.value, total: cartTotal() };
  }

  function restoreSnapshot(snap) {
    if (!snap) return;
    cart = {};
    Object.keys(snap.cart).forEach(function (id) {
      cart[id] = { product: snap.cart[id].product, quantity: snap.cart[id].quantity };
    });
    discountEl.value = snap.discount || '0';
    endSaleAttempt();
    renderCart();
  }

  /* ------------------------------------------------------------------ */
  /* Sale Completion & Receipts                                         */
=======
      busy = false;
      payConfirmBtn().disabled = false;
      showError('Network problem \u2014 the sale was NOT recorded. Try again.');
    });
  });

  function payConfirmBtn() { return document.getElementById('payConfirm'); }

  /* ------------------------------------------------------------------ */
  /* Result handling                                                     */
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  /* ------------------------------------------------------------------ */

  var doneModal = document.getElementById('doneModal');
  var pollTimer = null;

  function handleSaleResult(sale) {
<<<<<<< HEAD
=======
    cart = {};
    renderCart();
    searchInput.value = '';

>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    document.getElementById('donePending').hidden = true;
    document.getElementById('donePaid').hidden = true;
    document.getElementById('doneFailed').hidden = true;
    document.getElementById('donePrintError').hidden = true;

    if (sale.pending_mpesa) {
<<<<<<< HEAD
      cart = {};
      endSaleAttempt();
      renderCart();
      searchInput.value = '';
      broadcastDisplay('paying', {
        method: 'M-PESA',
        prompt_message: 'M-Pesa STK prompt sent to phone. Enter your PIN to approve ' + money(sale.total) + '.'
      });
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
      document.getElementById('donePending').hidden = false;
      openModal(doneModal);
      pollPayment(sale.number);
    } else if (sale.payment_status === 'paid') {
<<<<<<< HEAD
      lastSaleSnapshot = null;
      cart = {};
      endSaleAttempt();
      renderCart();
      searchInput.value = '';
      broadcastDisplay('paid', {
        method: sale.method_display || payMethod.toUpperCase(),
        order_number: sale.number,
        change: sale.change_given || 0
      });
      showPaid(sale);
    } else {
      restoreOnClose = true;
      document.getElementById('failedReason').textContent =
        sale.result_description || 'Payment did not go through.';
      broadcastDisplay('idle', { prompt_message: 'Payment not completed.' });
      document.getElementById('doneFailed').hidden = false;
      var closeBtn = document.getElementById('doneClose');
      if (closeBtn) closeBtn.textContent = 'Return to Till / Try Again';
=======
      showPaid(sale);
    } else {
      document.getElementById('failedReason').textContent =
        sale.result_description || 'The payment did not go through.';
      document.getElementById('doneFailed').hidden = false;
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
      openModal(doneModal);
    }
  }

  function showPaid(sale) {
    document.getElementById('doneSummary').textContent =
      sale.method_display + ' \u00b7 ' + money(sale.total) + ' \u00b7 ' + sale.number;

<<<<<<< HEAD
    document.getElementById('donePending').hidden = true;
    document.getElementById('doneFailed').hidden = true;
    document.getElementById('donePrintError').hidden = true;

    doneModal.dataset.receiptUrl = sale.receipt_url;
    doneModal.dataset.receiptNumber = sale.number;
    doneModal.dataset.pdfReceiptUrl = sale.pdf_receipt_url;

    document.getElementById('receiptLink').href = sale.receipt_url;
    document.getElementById('receiptPrint').href = sale.receipt_url + '?print=1&size=' + getPrinterSize();
    document.getElementById('receiptPdfDownload').href = sale.pdf_receipt_url + '?download=1&size=' + getPrinterSize();

    document.getElementById('donePaid').hidden = false;
    var closePaidBtn = document.getElementById('doneClose');
    if (closePaidBtn) closePaidBtn.textContent = 'Start New Sale';
    openModal(doneModal);

    // Auto-trigger thermal print via background iframe
    autoPrintReceipt(sale.receipt_url, sale.number);
  }

  /* Thermal Auto-Print */
=======
    // Store receipt URL for retry / download / view
    doneModal.dataset.receiptUrl = sale.receipt_url;
    doneModal.dataset.receiptNumber = sale.number;

    var link = document.getElementById('receiptLink');
    link.href = sale.receipt_url;
    document.getElementById('receiptPrint').href = sale.receipt_url + '?print=1';
    document.getElementById('receiptDownload').href = sale.receipt_url + '?download=1';

    document.getElementById('donePaid').hidden = false;
    document.getElementById('donePrintError').hidden = true;
    openModal(doneModal);

    // Auto-print receipt
    autoPrintReceipt(sale.receipt_url, sale.number);
  }

  /* ------------------------------------------------------------------ */
  /* Auto-print receipt                                                  */
  /* ------------------------------------------------------------------ */

>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  var printIframe = null;
  var printTimeout = null;

  function autoPrintReceipt(receiptUrl, orderNumber) {
<<<<<<< HEAD
    cleanupPrintIframe();
=======
    // Create a hidden iframe to load the receipt for printing
    cleanupPrintIframe();

>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    printIframe = document.createElement('iframe');
    printIframe.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;';
    printIframe.setAttribute('aria-hidden', 'true');
    printIframe.setAttribute('tabindex', '-1');

    var size = getPrinterSize();
    var autoUrl = receiptUrl + '?auto=1&size=' + size;

<<<<<<< HEAD
    var messageHandler = function (e) {
      if (!e.data || typeof e.data.type !== 'string') return;
      if (e.data.number !== orderNumber) return;
      clearTimeout(printTimeout);
    };
    window.addEventListener('message', messageHandler);
    printIframe._messageHandler = messageHandler;

    printTimeout = setTimeout(function () {}, 8000);
=======
    // Listen for messages from the iframe
    var messageHandler = function (e) {
      if (!e.data || typeof e.data.type !== 'string') return;
      if (e.data.number !== orderNumber) return;

      if (e.data.type === 'receipt-print-triggered') {
        clearTimeout(printTimeout);
        // Print was triggered successfully — show the sale complete state
        showPrintSuccess();
      } else if (e.data.type === 'receipt-print-failed') {
        clearTimeout(printTimeout);
        showPrintError(orderNumber);
      }
    };
    window.addEventListener('message', messageHandler);

    // Store handler reference for cleanup
    printIframe._messageHandler = messageHandler;

    // Fallback timeout: if no message received within 8 seconds, assume print dialog
    // was opened (beforeunload/afterprint not reliable across all browsers)
    printTimeout = setTimeout(function () {
      // Assume print dialog was shown — the user can print or cancel
      showPrintSuccess();
    }, 8000);

    printIframe.onload = function () {
      // iframe loaded; the receipt page script will auto-trigger print
    };

>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    document.body.appendChild(printIframe);
    printIframe.src = autoUrl;
  }

  function cleanupPrintIframe() {
    if (printTimeout) { clearTimeout(printTimeout); printTimeout = null; }
    if (printIframe) {
      if (printIframe._messageHandler) {
        window.removeEventListener('message', printIframe._messageHandler);
      }
      printIframe.src = 'about:blank';
      if (printIframe.parentNode) printIframe.parentNode.removeChild(printIframe);
      printIframe = null;
    }
  }

<<<<<<< HEAD
  document.getElementById('retryPrint').addEventListener('click', function () {
    var url = doneModal.dataset.receiptUrl;
    var num = doneModal.dataset.receiptNumber;
    if (url) autoPrintReceipt(url, num);
=======
  function showPrintSuccess() {
    // Print dialog was shown or print succeeded — all good
    // The done modal stays as-is with View/Print/Download options
  }

  function showPrintError(orderNumber) {
    // Print failed — show retry/download options
    var printErrorEl = document.getElementById('donePrintError');
    var paidEl = document.getElementById('donePaid');
    if (printErrorEl) {
      printErrorEl.hidden = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Manual print / retry / download from done modal                     */
  /* ------------------------------------------------------------------ */

  document.getElementById('retryPrint').addEventListener('click', function () {
    var url = doneModal.dataset.receiptUrl;
    var num = doneModal.dataset.receiptNumber;
    if (!url) return;
    document.getElementById('donePrintError').hidden = true;
    autoPrintReceipt(url, num);
  });

  document.getElementById('manualPrint').addEventListener('click', function () {
    var url = doneModal.dataset.receiptUrl;
    if (!url) return;
    var size = getPrinterSize();
    window.open(url + '?print=1&size=' + size, '_blank');
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  });

  document.getElementById('downloadReceipt').addEventListener('click', function () {
    var url = doneModal.dataset.receiptUrl;
    if (!url) return;
<<<<<<< HEAD
=======
    // Trigger download via a temporary link
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    var a = document.createElement('a');
    a.href = url + '?download=1';
    a.download = 'receipt-' + (doneModal.dataset.receiptNumber || '') + '.html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });

<<<<<<< HEAD
  /* M-Pesa Polling */
=======
  /* ------------------------------------------------------------------ */
  /* M-Pesa polling                                                      */
  /* ------------------------------------------------------------------ */

>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  function pollPayment(number) {
    clearInterval(pollTimer);
    var attempts = 0;
    pollTimer = setInterval(function () {
      attempts += 1;
<<<<<<< HEAD
      fetch(STATE_URL_BASE.replace('NUMBER', encodeURIComponent(number)), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin'
      })
=======
      fetch(STATE_URL_BASE.replace('NUMBER', encodeURIComponent(number)),
            { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        .then(function (r) { return r.json(); })
        .then(function (s) {
          if (s.payment_status === 'paid') {
            clearInterval(pollTimer);
            document.getElementById('pendingNote').hidden = true;
<<<<<<< HEAD
            lastSaleSnapshot = null;
            broadcastDisplay('paid', {
              method: 'M-PESA',
              order_number: s.number,
              change: 0
            });
            showPaid(s);
          } else if (s.payment_status === 'failed' || s.payment_status === 'cancelled') {
            clearInterval(pollTimer);
            restoreOnClose = true;
=======
            showPaid(s);
          } else if (s.payment_status === 'failed' || s.payment_status === 'cancelled') {
            clearInterval(pollTimer);
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
            document.getElementById('failedReason').textContent =
              s.result_description || 'The customer did not complete the payment.';
            document.getElementById('donePending').hidden = true;
            document.getElementById('doneFailed').hidden = false;
<<<<<<< HEAD
            var pollCloseBtn = document.getElementById('doneClose');
            if (pollCloseBtn) pollCloseBtn.textContent = 'Return to Till / Try Again';
            broadcastDisplay('idle', { prompt_message: 'Payment was not completed.' });
          } else if (attempts > 60) {
            clearInterval(pollTimer);
            var note = document.getElementById('pendingNote');
            note.textContent = 'Still waiting after 3 minutes. The sale stays pending until M-Pesa confirms or fails.';
            note.hidden = false;
          }
        })
        .catch(function () {});
=======
          } else if (attempts > 60) {
            clearInterval(pollTimer);
            var note = document.getElementById('pendingNote');
            note.textContent = 'Still waiting after 3 minutes. The sale stays pending until M-Pesa confirms or fails \u2014 check Sales history.';
            note.hidden = false;
          }
        })
        .catch(function () { /* transient; keep polling */ });
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    }, 3000);
  }

  document.getElementById('doneClose').addEventListener('click', function () {
    clearInterval(pollTimer);
    cleanupPrintIframe();
    closeModal(doneModal);
<<<<<<< HEAD
    if (restoreOnClose) {
      restoreOnClose = false;
      restoreSnapshot(lastSaleSnapshot);
      lastSaleSnapshot = null;
      flash('Sale was not completed — items restored to till.');
    } else {
      setCustomer(null);
    }
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    searchInput.focus();
  });

  /* ------------------------------------------------------------------ */
<<<<<<< HEAD
  /* Shortcuts & Modals                                                 */
  /* ------------------------------------------------------------------ */

  document.addEventListener('keydown', function (e) {
    if (e.key === 'F2') {
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    } else if (e.key === 'F4') {
      e.preventDefault();
      if (!payBtn.disabled && modal.hidden) payBtn.click();
    } else if (e.key === 'Escape') {
      if (!modal.hidden) closeModal(modal);
      else if (!newCustomerModal.hidden) closeModal(newCustomerModal);
      else if (displayOpen) closeCustomerDisplay();
      else if (!customerSearchPopover.hidden) customerSearchPopover.hidden = true;
    }
  });

  function openModal(m) {
    m.hidden = false;
    m.classList.add('open');
    document.body.classList.add('modal-open');
  }
  function closeModal(m) {
    m.hidden = true;
    m.classList.remove('open');
    document.body.classList.remove('modal-open');
  }
=======

  function openModal(m) { m.hidden = false; document.body.classList.add('modal-open'); }
  function closeModal(m) { m.hidden = true; document.body.classList.remove('modal-open'); }
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
  function showError(msg) { var el = document.getElementById('payError'); el.textContent = msg; el.hidden = false; }
  function hideError() { document.getElementById('payError').hidden = true; }

  var flashTimer = null;
  function flash(msg) {
    var el = document.createElement('div');
    el.className = 'message warning pos-flash';
    el.textContent = msg;
    document.body.appendChild(el);
    clearTimeout(flashTimer);
    flashTimer = setTimeout(function () { el.remove(); }, 3500);
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
<<<<<<< HEAD
  function escapeAttr(s) { return escapeHtml(s); }

  function saleToken() {
    if (!pendingSaleToken) {
      pendingSaleToken = (window.crypto && window.crypto.randomUUID)
        ? window.crypto.randomUUID()
        : 'pos-' + Date.now() + '-' + Math.random().toString(36).slice(2);
    }
    return pendingSaleToken;
  }

  function endSaleAttempt() { pendingSaleToken = null; }

  renderCart();
  loadCatalogue();
=======

  function saleToken() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'pos-' + Date.now() + '-' + Math.random().toString(36).slice(2);
  }

  renderCart();
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
})();
