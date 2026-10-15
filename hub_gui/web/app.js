(function () {
  'use strict';

  const HARNESSES = ['claude', 'codex', 'opencode', 'dsh'];
  const TYPE_LABELS = { plugin: '插件', skill: '技能', memory: '记忆' };
  const HEALTH_VARIANT = {
    ok: 'success',
    missing: 'warning',
    conflict: 'danger',
    orphan: 'warning',
    unknown: 'neutral',
    stale: 'warning',
    dirty: 'danger',
    drift: 'warning',
    'enable-drift': 'warning',
    'source-moved': 'danger',
    unregistered: 'danger',
    'no-baseline': 'neutral',
    unmanaged: 'neutral'
  };
  const CONTROL_TEXT = {
    direct: '直接控制',
    plugin: '由插件整体控制',
    readonly: '只读',
    unmanaged: '未纳入管理'
  };

  const state = { assets: [], harness: 'all', type: 'all', search: '' };
  let loadingInventory = false;

  function $(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function truncate(value, max) {
    const text = String(value == null ? '' : value);
    return text.length > (max || 80) ? text.slice(0, (max || 80) - 1) + '…' : text;
  }

  function healthVariant(health) {
    return HEALTH_VARIANT[health] || 'neutral';
  }

  function filterAssets(assets) {
    const harness = state.harness;
    const type = state.type;
    const query = state.search.trim().toLowerCase();
    return assets.filter(function (asset) {
      if (type !== 'all' && asset.type !== type) return false;
      if (harness !== 'all' && (!asset.harnesses || !asset.harnesses[harness])) return false;
      const cell = asset.harnesses && asset.harnesses[harness];
      if (!query) return true;
      const haystack = [
        asset.type, asset.id, asset.name, asset.path, asset.plugin,
        asset.skill_origin, Array.isArray(asset.scope) ? asset.scope.join(' ') : '',
        cell ? cell.detail : ''
      ].join(' ').toLowerCase();
      return haystack.indexOf(query) !== -1;
    });
  }

  function renderSummary() {
    const filtered = filterAssets(state.assets);
    const counts = { plugin: 0, skill: 0, memory: 0 };
    state.assets.forEach(function (a) { counts[a.type] = (counts[a.type] || 0) + 1; });
    const healthCounts = {};
    filtered.forEach(function (a) {
      Object.keys(a.harnesses || {}).forEach(function (h) {
        const key = a.harnesses[h].health || 'unknown';
        healthCounts[key] = (healthCounts[key] || 0) + 1;
      });
    });
    $('summary').innerHTML =
      '<div class="summary-stats">' +
        stat('总资产', state.assets.length) +
        stat('显示', filtered.length) +
        stat('插件', counts.plugin || 0) +
        stat('技能', counts.skill || 0) +
        stat('记忆', counts.memory || 0) +
      '</div>' +
      '<div class="summary-health">' + Object.keys(healthCounts).map(function (k) {
        return '<sl-badge variant="' + healthVariant(k) + '" pill>' +
          escapeHtml(k) + ' ' + healthCounts[k] + '</sl-badge>';
      }).join('') + '</div>';
    $('summaryLabel').textContent = '摘要 · 共 ' + filtered.length + ' 项';
  }

  function stat(label, value) {
    return '<div class="stat"><span class="stat-label">' + escapeHtml(label) + '</span>' +
      '<strong>' + escapeHtml(String(value)) + '</strong></div>';
  }

  function controlWidget(asset, harness, cell) {
    if (cell.control === 'direct') {
      const checked = !!cell.desired;
      return '<sl-switch class="direct-switch" ' +
        'data-asset-type="' + escapeHtml(asset.type) + '"' +
        ' data-asset-name="' + escapeHtml(asset.name) + '"' +
        ' data-plugin="' + escapeHtml(asset.plugin || '') + '"' +
        ' data-harness="' + escapeHtml(harness) + '"' +
        ' checked size="small"></sl-switch>';
    }
    if (cell.control === 'plugin') {
      return '<sl-badge variant="neutral" pill class="badge-control" title="由插件整体控制">由插件控制</sl-badge>';
    }
    if (cell.control === 'readonly') {
      return '<sl-badge variant="neutral" pill class="badge-control">只读</sl-badge>';
    }
    if (cell.control === 'unmanaged') {
      return '<sl-badge variant="neutral" pill class="badge-control">未管理</sl-badge>';
    }
    const control = CONTROL_TEXT[cell.control] || cell.control || '—';
    return '<sl-badge variant="neutral" pill class="badge-control">' + escapeHtml(control) + '</sl-badge>';
  }

  function renderCell(asset, harness) {
    const cell = asset.harnesses && asset.harnesses[harness];
    if (!cell) {
      return '<td class="cell-na"><span>—</span></td>';
    }
    const variant = healthVariant(cell.health || 'unknown');
    const health = escapeHtml(cell.health || 'unknown');
    const detail = escapeHtml(cell.detail || '');
    const shortDetail = escapeHtml(truncate(cell.detail || '', 100));
    const desired = cell.desired ? 'on' : 'off';
    const actual = cell.actual ? 'on' : (cell.actual === null ? '未知' : 'off');
    return '<td class="cell">' +
      '<div class="cell-top">' +
        '<sl-badge variant="' + variant + '" pill>' + health + '</sl-badge>' +
        '<span class="state-indicator desired">desired ' + desired + '</span>' +
      '</div>' +
      controlWidget(asset, harness, cell) +
      '<div class="state-indicator actual">actual ' + escapeHtml(String(actual)) + '</div>' +
      '<div class="cell-detail" title="' + detail + '">' + shortDetail + '</div>' +
      '</td>';
  }

  function renderRow(asset) {
    const typeLabel = TYPE_LABELS[asset.type] || asset.type;
    const pluginTag = asset.plugin ? '<sl-tag size="small" pill>插件 · ' + escapeHtml(asset.plugin) + '</sl-tag>' : '';
    const originTag = asset.skill_origin ? '<sl-tag size="small" pill>' + escapeHtml(asset.skill_origin) + '</sl-tag>' : '';
    const memoryTag = asset.type === 'memory' ? '<sl-tag size="small" pill variant="neutral">readonly</sl-tag>' : '';
    const cells = HARNESSES.map(function (h) { return renderCell(asset, h); }).join('');
    return '<tr>' +
      '<td class="asset-col">' +
        '<div class="asset-name">' + escapeHtml(asset.name) + '</div>' +
        '<div class="asset-id">' + escapeHtml(asset.id) + '</div>' +
        '<div class="asset-meta"><sl-tag size="small" pill variant="primary">' + typeLabel + '</sl-tag>' + pluginTag + originTag + memoryTag + '</div>' +
      '</td>' +
      cells +
    '</tr>';
  }

  function renderTable() {
    const filtered = filterAssets(state.assets);
    $('matrixBody').innerHTML = filtered.length
      ? filtered.map(renderRow).join('')
      : '<tr><td colspan="5" class="empty">无匹配资产</td></tr>';
    $('status').textContent = '数据已加载：' + state.assets.length + ' 项资产，筛选显示 ' + filtered.length + ' 项。';
    $('status').classList.remove('error');
  }

  function onFilterChange() {
    state.harness = $('harnessFilter').value;
    state.type = $('typeFilter').value;
    state.search = $('searchInput').value || '';
    renderSummary();
    renderTable();
  }

  function render(data) {
    state.assets = data && Array.isArray(data.assets) ? data.assets : [];
    renderSummary();
    renderTable();
  }

  function showError(detail) {
    const message = typeof detail === 'string' ? detail : (detail && detail.detail) || '加载失败';
    $('status').textContent = message;
    $('status').classList.add('error');
    $('matrixBody').innerHTML = '<tr><td colspan="5" class="empty">' + escapeHtml(message) + '</td></tr>';
  }

  function showToggleResult(message, isError) {
    const el = $('toggleStatus');
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('error', !!isError);
    el.classList.toggle('success', !isError);
  }

  function loadInventory() {
    if (loadingInventory) return;
    loadingInventory = true;
    $('status').textContent = '正在加载 hub inventory…';
    fetch('/api/inventory')
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (body) {
            showError(body.detail || res.statusText);
            throw new Error('api-error');
          });
        }
        return res.json();
      })
      .then(render)
      .catch(function (err) {
        if (err && err.message === 'api-error') return;
        showError(err.message || '加载失败');
      })
      .finally(function () {
        loadingInventory = false;
      });
  }

  function toggleCell(sw) {
    const assetType = sw.getAttribute('data-asset-type');
    const name = sw.getAttribute('data-asset-name');
    const plugin = sw.getAttribute('data-plugin') || null;
    const harness = sw.getAttribute('data-harness');
    const target = sw.checked ? 'on' : 'off';
    const previous = sw.checked;

    if (target === 'off') {
      const ok = window.confirm('确定要关闭 ' + assetType + ' ' + name + ' @ ' + harness + ' 吗？');
      if (!ok) {
        sw.checked = true;
        return;
      }
    }

    sw.disabled = true;

    fetch('/api/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_type: assetType,
        name: name,
        harness: harness,
        state: target,
        plugin: plugin,
        dry_run: false
      })
    })
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok || !body.ok) {
            const message = body && (body.detail || (body.error && body.error.message)) || ('toggle 失败（HTTP ' + res.status + '）');
            throw new Error(message);
          }
          const data = body.data || {};
          const summary = data.results && data.results.length
            ? data.results.map(function (r) { return r.harness + ': ' + r.status + (r.detail ? '（' + r.detail + '）' : ''); }).join('；')
            : ('action ' + data.action + ' 已返回');
          showToggleResult('已执行 ' + assetType + ' ' + name + ' @ ' + harness + ' → ' + target + '：' + summary, false);
        });
      })
      .catch(function (err) {
        showToggleResult(err.message || 'toggle 失败', true);
        sw.checked = previous;
      })
      .finally(function () {
        sw.disabled = false;
        loadInventory();
      });
  }

  function onCellClick(event) {
    const sw = event.target.closest('sl-switch.direct-switch');
    if (!sw || sw.disabled) return;
    toggleCell(sw);
  }

  function init() {
    $('harnessFilter').addEventListener('sl-change', onFilterChange);
    $('typeFilter').addEventListener('sl-change', onFilterChange);
    $('searchInput').addEventListener('input', onFilterChange);
    $('matrixBody').addEventListener('click', onCellClick);
    $('refreshBtn').addEventListener('click', loadInventory);
    loadInventory();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
