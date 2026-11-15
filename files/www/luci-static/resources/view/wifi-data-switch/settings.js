'use strict';
'require view';
'require rpc';
'require poll';
'require ui';

var api = {};
[['status', []], ['configure', ['mode', 'ssid', 'encryption', 'wifi_key', 'failover', 'band']],
 ['scan', []]].forEach(function(entry) {
    api[entry[0]] = rpc.declare({ object: 'wifi-data-switch', method: entry[0], params: entry[1], expect: {} });
});
function notify(result) {
    ui.addNotification(null, E('p', {}, [result.message || (result.ok ? '操作完成。' : '操作未完成。')]), result.ok ? 'info' : 'warning');
}
function row(label, input, help) {
    return E('div', { 'class': 'cbi-value' }, [E('label', { 'class': 'cbi-value-title' }, [label]),
        E('div', { 'class': 'cbi-value-field' }, help ? [input, E('div', { 'class': 'cbi-value-description' }, [help])] : [input])]);
}
function button(text, action, primary) {
    var b = E('button', { 'class': 'cbi-button ' + (primary ? 'cbi-button-apply' : 'cbi-button-action'),
        'style': 'margin:4px 8px 4px 0', 'click': function() {
            b.disabled = true;
            return Promise.resolve().then(action).catch(function() {
                notify({ ok: false, message: '请求未完成，请查看当前连接状态后重试。' });
            }).finally(function() { b.disabled = false; });
        } }, [text]);
    return b;
}
return view.extend({
    handleSaveApply: null,
    handleSave: null,
    handleReset: null,
    load: function() { return api.status(); },
    render: function(initial) {
        var cfg = initial.settings || {};
        var modes = { split: 'OpenClash 分流', wifi: '全部走 Wi-Fi', mobile: '全部走移动数据' };
        var routeLabel = function(v) { return v === 'wifi' ? 'Wi-Fi' : '移动数据'; };
        var cards = E('div', { 'style': 'display:flex;gap:14px;flex-wrap:wrap;margin:16px 0' });
        var summary = E('div');
        var lastCounters = {};
        function card(title, state, lines, good) {
            return E('div', { 'class': 'cbi-section', 'style': 'flex:1;min-width:240px;padding:18px;border-left:4px solid ' + (good ? '#27875b' : '#bd8427') },
                [E('h3', {}, [title]), E('strong', {}, [state])].concat(lines.map(function(line) { return E('div', { 'style': 'margin-top:7px' }, [line]); })));
        }
        function speed(name, info) {
            var now = Date.now(), prev = lastCounters[name], c = info.counters || {};
            lastCounters[name] = { time: now, tx: c.tx_bytes, rx: c.rx_bytes };
            if (!prev || c.tx_bytes == null || now <= prev.time) return '正在读取流量…';
            var tx = Math.max(0, c.tx_bytes - prev.tx) * 8 / ((now - prev.time) * 1000);
            var rx = Math.max(0, c.rx_bytes - prev.rx) * 8 / ((now - prev.time) * 1000);
            return '上传 ' + tx.toFixed(2) + ' / 下载 ' + rx.toFixed(2) + ' Mbps';
        }
        function update(s) {
            var w = s.wifi || {}, m = s.mobile || {}, h = s.health || {}, wh = h.wifi || {}, mh = h.mobile || {};
            cards.replaceChildren(
                card('Wi-Fi', wh.online ? '已联网' : (w.up ? '已连接 · 待认证或联网检测中' : '未连接'),
                    [w.ssid || (s.settings || {}).ssid || '未设置', '地址：' + ((w.addresses || []).join(', ') || '—'),
                     '信号：' + (w.signal ? w.signal + ' dBm' : '—') + ' · ' + (w.frequency ? (Number(w.frequency) > 4000 ? '5 GHz' : '2.4 GHz') : '—'), speed('wifi', w)], wh.online),
                card('移动数据', mh.online ? '已联网' : (m.up ? '蜂窝已连接 · 检测中或网络不可用' : '未连接'),
                    ['地址：' + ((m.addresses || []).join(', ') || '—'), '接口：' + (m.device || '—'), speed('mobile', m)], mh.online));
            var savedMode = s.mode || (s.settings || {}).mode;
            var normalDirect = savedMode === 'mobile' ? 'mobile' : 'wifi';
            var normalProxy = savedMode === 'wifi' ? 'wifi' : 'mobile';
            var fallback = s.ready && (s.direct !== normalDirect || s.proxy !== normalProxy);
            var switchedAt = s.last_switch && s.last_switch.time ? new Date(s.last_switch.time * 1000).toLocaleString() : '尚无记录';
            summary.replaceChildren(E('p', {}, ['当前模式：' + (modes[savedMode] || '初始化中')]),
                E('p', {}, [E('strong', {}, ['直连 → ' + routeLabel(s.direct)]), '　　', E('strong', {}, ['OpenClash 代理 → ' + routeLabel(s.proxy)])]),
                E('p', {}, [s.ready ? (s.clash_bound ? (fallback ? '当前正在使用备用出口；原出口恢复后自动回切。' : '分流规则已就绪，正在自动监测两条出口。') : '正在准备 OpenClash 绑定；暂由移动数据保持连接。') : '监测服务正在启动或已停止。']),
                E('p', {}, ['最近出口变化：' + switchedAt]),
                E('small', {}, ['连续3次检测失败转移，连续2次成功恢复；检测周期约10–20秒。切换可能使已有连接重新建立。']));

        }
        update(initial);
        poll.add(function() { return api.status().then(update); }, 5);

        var mode = E('select', { 'class': 'cbi-input-select' }, Object.keys(modes).map(function(k) { return E('option', { value: k, selected: cfg.mode === k ? '' : null }, [modes[k]]); }));
        mode.value = cfg.mode || 'split';
        var ssid = E('input', { 'class': 'cbi-input-text', 'type': 'text', 'value': cfg.ssid || '', 'maxlength': '32' });
        var encryption = E('select', { 'class': 'cbi-input-select' }, [['none', '开放网络'], ['psk2', 'WPA2 密码'], ['sae', 'WPA3 SAE'], ['sae-mixed', 'WPA2 / WPA3']].map(function(v) { return E('option', { value: v[0] }, [v[1]]); }));
        encryption.value = cfg.encryption || 'none';
        var band = E('select', { 'class': 'cbi-input-select' }, [E('option', { value: '5g' }, ['5 GHz（优先使用）']), E('option', { value: '2g' }, ['2.4 GHz'])]);band.value = cfg.band || '5g';
        var key = E('input', { 'class': 'cbi-input-password', 'type': 'password', 'autocomplete': 'new-password', 'placeholder': '留空保留已保存的无线密码' });
        var failover = E('input', { 'type': 'checkbox', 'checked': cfg.failover !== false ? '' : null });
        failover.checked = cfg.failover !== false;
        var scanResult = E('div', { 'style': 'margin:8px 0' });
        var scanButton = button('扫描附近 Wi-Fi', function() {
            return api.scan().then(function(r) {
                var seen = {}, entries = (r.results || []).filter(function(v) { if (!v.ssid || seen[v.ssid]) return false;seen[v.ssid] = true;return true; });
                scanResult.replaceChildren.apply(scanResult, entries.length ? entries.map(function(v) {
                    return button(v.ssid + ' · ' + (v.signal == null ? '信号未知' : v.signal + ' dBm'), function() {
                        ssid.value = v.ssid;
                        encryption.value = v.encryption && v.encryption.enabled ? 'psk2' : 'none';
                        band.value = Number(v.frequency) > 4000 ? '5g' : '2g';
                    }, false);
                }) : [E('p', {}, ['未发现可用网络。扫描期间当前 Wi-Fi 可能有短暂波动。'])]);
            });
        }, false);
        var settings = E('div', { 'class': 'cbi-section' }, [E('h3', {}, ['出口与无线设置']),
            row('上网模式', mode, '分流模式遵循 OpenClash 当前规则：DIRECT 使用 Wi-Fi，代理节点使用移动数据。'),
            row('自动故障转移', failover, '任一出口不可用时使用另一条；原出口连续检测恢复后自动回切。'),
            row('无线名称（SSID）', ssid), row('无线频段', band), row('无线加密', encryption), row('无线密码', key),
            row('网络扫描', E('div', {}, [scanButton, scanResult])),
            button('保存并应用', function() { return api.configure(mode.value, ssid.value, encryption.value, key.value, String(failover.checked), band.value).then(function(r) { if (r.ok) key.value = '';notify(r); }); }, true)]);

        return E('div', {}, [E('h2', {}, ['Wi-Fi / 数据切换']),
            E('p', {}, ['保持 Wi-Fi 与移动数据同时在线，为下层设备选择出口，并与 OpenClash 配合分流。']), cards,
            E('div', { 'class': 'cbi-section', 'style': 'padding:16px' }, [summary]), settings]);
    }
});
