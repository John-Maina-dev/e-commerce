/* Point-of-Sale terminal. The browser only describes intent — every price,
   stock check and total is recomputed server-side at checkout. */
(function () {
  'use strict';

  var root = document.getElementById('posRoot');
  if (!root) return;

  var SEARCH_URL = root.dataset.searchUrl;
  var CHECKOUT_URL = root.dataset.checkoutUrl;
  var STATE_URL_BASE = root.dataset.stateUrlBase;
  var CURRENCY = root.dataset.currency || 'KES';
  var CAN_DISCOUNT = root.dataset.canDiscount === '1';
  var CSRF = root.querySelector('[name=csrfmiddlewaretoken]').value;

  var searchInput = document.getElementById('posSearch');
  var resultsBox = document.getElementById('posResults');
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
    }
    return row;
  }

  function showResults(list) {
    resultsBox.innerHTML = '';
    list.forEach(function (p) { resultsBox.appendChild(renderResult(p)); });
    resultsBox.hidden = list.length === 0;
    if (list.length) {
      quickBox.hidden = true;
    }
  }

  function doSearch(q, autoAddSingle) {
    return fetch(SEARCH_URL + '?q=' + encodeURIComponent(q), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin'
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var results = data.results || [];
        if (autoAddSingle && results.length === 1 && !results[0].out_of_stock) {
          addToCart(results[0]);
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
  });

  searchInput.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    var q = searchInput.value.trim();
    if (!q) return;
    doSearch(q, true);
  });

  document.addEventListener('click', function (e) {
    if (!resultsBox.contains(e.target) && e.target !== searchInput) resultsBox.hidden = true;
  });
  document.getElementById('posSearchBtn').addEventListener('click', function () {
    doSearch(searchInput.value.trim(), true);
  });

  /* ------------------------------------------------------------------ */
  /* Cart                                                                */
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
    renderCart();
  }

  function setQty(id, qty) {
    var entry = cart[id];
    if (!entry) return;
    qty = Math.max(0, Math.min(qty, entry.product.stock));
    if (qty === 0) { delete cart[id]; } else { entry.quantity = qty; }
    renderCart();
  }

  function lineTotal(entry) {
    return Number(entry.product.price) * entry.quantity;
  }

  function cartSubtotal() {
    return Object.keys(cart).reduce(function (sum, id) { return sum + lineTotal(cart[id]); }, 0);
  }

  function discountValue() {
    var d = CAN_DISCOUNT && discountEl ? parseFloat(discountEl.value || '0') : 0;
    return isFinite(d) && d > 0 ? Math.min(d, cartSubtotal()) : 0;
  }

  function renderCart() {
    var ids = Object.keys(cart);
    cartBody.innerHTML = '';
    if (!ids.length) {
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
    renderCart();
  });

  /* ------------------------------------------------------------------ */
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
  /* Payment                                                             */
  /* ------------------------------------------------------------------ */

  var modal = document.getElementById('payModal');
  var payMethod = 'cash';
  var busy = false;

  payBtn.addEventListener('click', function () {
    if (!Object.keys(cart).length) return;
    document.getElementById('payTotalLabel').textContent = money(cartSubtotal() - discountValue());
    document.getElementById('cashReceived').value = (cartSubtotal() - discountValue()).toFixed(2);
    updateChange();
    openModal(modal);
    selectMethod('cash');
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

  document.getElementById('payClose').addEventListener('click', function () { closeModal(modal); });
  modal.addEventListener('click', function (e) { if (e.target === modal) closeModal(modal); });

  document.getElementById('payConfirm').addEventListener('click', function () {
    if (busy) return;
    hideError();

    if (payMethod === 'cash') {
      var received = parseFloat(document.getElementById('cashReceived').value || '0');
      if (received < cartSubtotal() - discountValue()) {
        showError('Cash received is less than the total.');
        return;
      }
    }

    busy = true;
    this.disabled = true;

    var items = Object.keys(cart).map(function (id) {
      return { id: Number(id), quantity: cart[id].quantity };
    });
    var body = {
      items: items,
      payment_method: payMethod,
      discount: CAN_DISCOUNT ? discountValue() : 0,
      token: saleToken(),
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
        showError(r.data.error || 'The sale could not be completed.');
        return;
      }
      closeModal(modal);
      handleSaleResult(r.data.sale);
    }).catch(function () {
      busy = false;
      payConfirmBtn().disabled = false;
      showError('Network problem \u2014 the sale was NOT recorded. Try again.');
    });
  });

  function payConfirmBtn() { return document.getElementById('payConfirm'); }

  /* ------------------------------------------------------------------ */
  /* Result handling                                                     */
  /* ------------------------------------------------------------------ */

  var doneModal = document.getElementById('doneModal');
  var pollTimer = null;

  function handleSaleResult(sale) {
    cart = {};
    renderCart();
    searchInput.value = '';

    document.getElementById('donePending').hidden = true;
    document.getElementById('donePaid').hidden = true;
    document.getElementById('doneFailed').hidden = true;
    document.getElementById('donePrintError').hidden = true;

    if (sale.pending_mpesa) {
      document.getElementById('donePending').hidden = false;
      openModal(doneModal);
      pollPayment(sale.number);
    } else if (sale.payment_status === 'paid') {
      showPaid(sale);
    } else {
      document.getElementById('failedReason').textContent =
        sale.result_description || 'The payment did not go through.';
      document.getElementById('doneFailed').hidden = false;
      openModal(doneModal);
    }
  }

  function showPaid(sale) {
    document.getElementById('doneSummary').textContent =
      sale.method_display + ' \u00b7 ' + money(sale.total) + ' \u00b7 ' + sale.number;

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

  var printIframe = null;
  var printTimeout = null;

  function autoPrintReceipt(receiptUrl, orderNumber) {
    // Create a hidden iframe to load the receipt for printing
    cleanupPrintIframe();

    printIframe = document.createElement('iframe');
    printIframe.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;';
    printIframe.setAttribute('aria-hidden', 'true');
    printIframe.setAttribute('tabindex', '-1');

    var size = getPrinterSize();
    var autoUrl = receiptUrl + '?auto=1&size=' + size;

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
  });

  document.getElementById('downloadReceipt').addEventListener('click', function () {
    var url = doneModal.dataset.receiptUrl;
    if (!url) return;
    // Trigger download via a temporary link
    var a = document.createElement('a');
    a.href = url + '?download=1';
    a.download = 'receipt-' + (doneModal.dataset.receiptNumber || '') + '.html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });

  /* ------------------------------------------------------------------ */
  /* M-Pesa polling                                                      */
  /* ------------------------------------------------------------------ */

  function pollPayment(number) {
    clearInterval(pollTimer);
    var attempts = 0;
    pollTimer = setInterval(function () {
      attempts += 1;
      fetch(STATE_URL_BASE.replace('NUMBER', encodeURIComponent(number)),
            { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (s) {
          if (s.payment_status === 'paid') {
            clearInterval(pollTimer);
            document.getElementById('pendingNote').hidden = true;
            showPaid(s);
          } else if (s.payment_status === 'failed' || s.payment_status === 'cancelled') {
            clearInterval(pollTimer);
            document.getElementById('failedReason').textContent =
              s.result_description || 'The customer did not complete the payment.';
            document.getElementById('donePending').hidden = true;
            document.getElementById('doneFailed').hidden = false;
          } else if (attempts > 60) {
            clearInterval(pollTimer);
            var note = document.getElementById('pendingNote');
            note.textContent = 'Still waiting after 3 minutes. The sale stays pending until M-Pesa confirms or fails \u2014 check Sales history.';
            note.hidden = false;
          }
        })
        .catch(function () { /* transient; keep polling */ });
    }, 3000);
  }

  document.getElementById('doneClose').addEventListener('click', function () {
    clearInterval(pollTimer);
    cleanupPrintIframe();
    closeModal(doneModal);
    searchInput.focus();
  });

  /* ------------------------------------------------------------------ */

  function openModal(m) { m.hidden = false; document.body.classList.add('modal-open'); }
  function closeModal(m) { m.hidden = true; document.body.classList.remove('modal-open'); }
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

  function saleToken() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'pos-' + Date.now() + '-' + Math.random().toString(36).slice(2);
  }

  renderCart();
})();
