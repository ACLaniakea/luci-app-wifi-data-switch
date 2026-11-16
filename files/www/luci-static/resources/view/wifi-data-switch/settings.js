'use strict';
'require view';
'require rpc';
'require poll';
'require ui';

var api = {};
[['status', []], ['configure', ['mode', 'ssid', 'encryption', 'wifi_key', 'failover', 'band', 'boost_enabled', 'boost_strategy', 'boost_devices', 'boost_domains', 'daily_mib', 'monthly_mib', 'billing_day', 'mobile_daily_mib', 'mobile_monthly_mib', 'boost_device_mode']],
 ['scan', []], ['devices', []], ['apply', []]].forEach(function(entry) {
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
        var usagePanel = E('div', { 'class': 'cbi-section', style: 'padding:16px' });
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
            var usage = s.usage || {}, networks = usage.networks || {}, wifiUsage = networks.wifi || {}, mobileUsage = networks.mobile || {}, daily = usage.daily || {}, monthly = usage.monthly || {};
            function amount(v) { v = Number(v || 0); return v >= 1073741824 ? (v / 1073741824).toFixed(2) + ' GiB' : (v / 1048576).toFixed(1) + ' MiB'; }
            function budget(v) { return amount(v.used) + ' / ' + (v.limit ? amount(v.limit) : '不限额'); }
            usagePanel.replaceChildren(E('h3', {}, ['流量用量']),
                E('p', {}, ['Wi-Fi 总用量 · 今日：' + amount((wifiUsage.daily || {}).used) + ' · 本周期：' + amount((wifiUsage.monthly || {}).used)]),
                E('p', {}, ['移动总用量 · 今日：' + budget(mobileUsage.daily || {}) + ' · 本周期：' + budget(mobileUsage.monthly || {})]),
                E('small', {}, [mobileUsage.started_at ? '总量统计开始于 ' + new Date(mobileUsage.started_at * 1000).toLocaleString() + '；此前用量未计入。' : '总量统计初始化中。']),
                E('h4', {}, ['加速移动流量（独立统计）']), E('p', {}, ['今日：' + budget(daily)]), E('p', {}, ['本计费周期：' + budget(monthly)]),
                E('p', {}, [usage.ready ? (usage.mobile_total_exceeded ? '移动总量到额：全部走 Wi-Fi，移动出口已停用。' : usage.exceeded ? '加速额度到额：暂停加速，代理仍按原策略运行。' : (daily.warning || monthly.warning ? '用量已达额度的 80%。' : '只统计双网加速使用的移动流量，含上传和下载。')) : '流量计量等待就绪；此时暂停双网加速。']),
                E('small', {}, ['路由器估算，非运营商账单。约每轮检测更新、每分钟保存；突然断电可能少计最后一分钟。跨日连接按采样时刻归属。']));
            var savedMode = s.mode || (s.settings || {}).mode;
            var normalDirect = savedMode === 'mobile' ? 'mobile' : 'wifi';
            var normalProxy = savedMode === 'wifi' ? 'wifi' : 'mobile';
            var fallback = s.ready && (s.direct !== normalDirect || s.proxy !== normalProxy);
            var switchedAt = s.last_switch && s.last_switch.time ? new Date(s.last_switch.time * 1000).toLocaleString() : '尚无记录';
            summary.replaceChildren(E('p', {}, [s.pending ? '有已保存但未应用的设置。' : '当前设置已应用。']),
                E('p', {}, [s.quota_wifi_only ? '移动总量到额，当前强制全部走 Wi-Fi；Wi-Fi 断线时不回退移动网络。' : '按所选模式自动选择出口。']),
                E('p', {}, ['当前模式：' + (modes[savedMode] || '初始化中')]),
                E('p', {}, [E('strong', {}, ['直连 → ' + routeLabel(s.direct)]), '　　', E('strong', {}, ['OpenClash 代理 → ' + routeLabel(s.proxy)])]),
                E('p', {}, [s.ready ? (s.clash_bound ? (fallback ? '当前正在使用备用出口；原出口恢复后自动回切。' : '分流规则已就绪，正在自动监测两条出口。') : '正在准备 OpenClash 绑定；暂由移动数据保持连接。') : '监测服务正在启动或已停止。']),
                E('p', {}, ['最近出口变化：' + switchedAt]),
                E('p', {}, ['双网加速：' + (s.boost && s.boost.active && s.clash_bound ? '运行中' : (s.boost && s.boost.reason ? s.boost.reason : '已关闭'))]),
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
        var boostEnabled = E('input', { type: 'checkbox' }); boostEnabled.checked = !!cfg.boost_enabled;
        var boostDevices = E('textarea', { 'class': 'cbi-input-textarea', rows: '3', placeholder: '每行一个设备 IPv4 或网段' }, [cfg.boost_devices || '']); boostDevices.value = cfg.boost_devices || '';
        var recommendedDomains = (initial.recommended_domains || ['download.windowsupdate.com', 'dl.delivery.mp.microsoft.com', 'mirrors.tuna.tsinghua.edu.cn', 'mirrors.ustc.edu.cn']).join('\n');
        var boostDomains = E('textarea', { 'class': 'cbi-input-textarea', rows: '3', placeholder: '每行一个域名，包含其子域名' }, [cfg.boost_domains || recommendedDomains]); boostDomains.value = cfg.boost_domains || recommendedDomains;
        var deviceMode = E('select', { 'class': 'cbi-input-select' }, [E('option', {value:'all'}, ['全部设备']), E('option', {value:'whitelist'}, ['仅选中设备（白名单）']), E('option', {value:'blacklist'}, ['排除选中设备（黑名单）'])]);
        deviceMode.value = cfg.boost_device_mode || (cfg.boost_devices ? 'whitelist' : 'all');
        var deviceList = E('div', { 'class': 'wds-devices-grid' }), inventory = [];
        var deviceSummary = E('summary', { 'class': 'wds-device-summary' });
        function renderDevices() {
            var selected = boostDevices.value.split(/[\s,]+/).filter(Boolean);
            var modeLabel = {all:'全部设备',whitelist:'白名单',blacklist:'黑名单'}[deviceMode.value];
            deviceSummary.replaceChildren(E('strong', {}, ['选择设备']), E('span', {style:'margin-left:12px;opacity:.75'}, [modeLabel + (deviceMode.value === 'all' ? '' : ' · 已选 ' + new Set(selected).size + ' 项') + ' · ' + inventory.length + ' 条设备记录']));
            deviceList.replaceChildren.apply(deviceList, inventory.length ? inventory.map(function(d) {
                var check = E('input', {type:'checkbox'});
                check.checked = deviceMode.value === 'all' || selected.indexOf(d.ip) >= 0 || selected.indexOf(d.ip + '/32') >= 0;
                check.disabled = deviceMode.value === 'all';
                check.addEventListener('change', function() {
                    var values = boostDevices.value.split(/[\s,]+/).filter(function(v) {return v && v !== d.ip && v !== d.ip + '/32';});
                    if (check.checked) values.push(d.ip);
                    boostDevices.value = values.join('\n');
                    renderDevices();
                });
                var state = d.state === 'recent' ? '最近通信' : (d.state === 'lease' ? '有租约，在线未确认' : '缓存记录，在线未确认');
                return E('label', { 'class': 'wds-device-card' + (check.checked ? ' wds-device-selected' : '') }, [check,
                    E('div', {style:'min-width:0;flex:1'}, [E('div', { 'class':'wds-device-name' }, [d.name || '未命名设备']),
                    E('div', { 'class':'wds-device-ip' }, [d.ip]), E('small', {style:'opacity:.65;word-break:break-all'}, [d.mac || '']),
                    E('div', { 'class': 'wds-device-state' + (d.state === 'recent' ? ' wds-device-recent' : '') }, [state])])]);
            }) : [E('p', {}, ['暂无设备记录，可刷新或手动填写。'])]);
        }
        function loadDevices() { return api.devices().then(function(r) { inventory = r.devices || [];renderDevices(); }); }
        deviceMode.addEventListener('change', renderDevices);
        boostDevices.addEventListener('change', renderDevices);
        loadDevices().catch(function() { deviceList.replaceChildren(E('p', {}, ['设备列表读取失败，请刷新重试。'])); });
        var devicePicker = E('div', {}, [deviceMode, E('details', { 'class':'wds-device-picker' }, [deviceSummary, E('div', {style:'padding:0 12px 12px'}, [button('刷新设备列表', loadDevices, false), deviceList])])]);
        var domainPicker = E('div', {}, [boostDomains, button('恢复默认', function() {
            boostDomains.value = recommendedDomains;
        }, false)]);
        function quotaInput(saved) {
            var factor = 1024;
            var input = E('input', { 'class': 'cbi-input-text', type: 'number', min: '0', step: 'any', value: Number(saved || 0) / factor });
            var unit = E('select', { 'class': 'cbi-input-select', style: 'width:auto;margin-left:8px' }, [E('option', { value: '1024' }, ['GiB']), E('option', { value: '1' }, ['MiB'])]);
            unit.value = '1024';
            unit.addEventListener('change', function() {
                var next = Number(unit.value);
                if (input.value !== '' && Number.isFinite(Number(input.value))) input.value = Number(input.value) * factor / next;
                factor = next;
            });
            return { widget: E('span', {}, [input, unit]), mib: function() {
                var value = Number(input.value) * factor;
                if (!Number.isFinite(value) || value < 0 || value > 100000000) throw new Error('额度超出范围');
                return String(Math.round(value));
            } };
        }
        var dailyLimit = quotaInput(cfg.daily_mib);
        var monthlyLimit = quotaInput(cfg.monthly_mib);
        var mobileDaily = quotaInput(cfg.mobile_daily_mib);
        var mobileMonthly = quotaInput(cfg.mobile_monthly_mib);
        var billingDay = E('input', { type: 'number', min: '1', max: '28', value: cfg.billing_day || 1 });
        var accelerationPanel = E('div', { 'class': 'cbi-section' }, [E('h3', {}, ['加速范围']),
            row('直连双网加速', boostEnabled, '仅分流模式下生效；只处理指定范围内原本 DIRECT 的 TCP 连接。新连接轮流使用双网，单连接不叠加带宽。'),
            row('设备范围', devicePicker, '默认全部设备。白名单只允许所选设备，黑名单排除所选设备。列表来自租约和邻居缓存，不保证设备此刻在线。'), row('手动 IP／网段', boostDevices, '可选：用于白名单或黑名单。IP 可能变化，长期使用建议设置静态租约。'), row('加速域名', domainPicker, '只有设备范围和域名同时匹配，且原规则明确走 DIRECT，才参与加速。清空域名不能启用加速。'),
            E('p', {}, ['建议仅填写下载域名。游戏、会议、支付和远程控制设备不要整体加入吞吐优先。'])]);
        var quotaPanel = E('div', { 'class': 'cbi-section' }, [E('h3', {}, ['流量限额']), row('每日移动总额度', mobileDaily.widget, '含代理、普通上网和加速；0 表示不限额'), row('每月移动总额度', mobileMonthly.widget, '达到后代理和直连全部走 Wi-Fi，停用移动出口；Wi-Fi 不可用时不会回退到移动数据'), row('每日加速额度', dailyLimit.widget, '0 表示不限额'), row('每月加速额度', monthlyLimit.widget, '只限制额外加速流量，不限制原有代理流量'), row('每月结算日', billingDay, '1–28 日。修改周期不会清空已有用量。'), E('p', {}, ['加速额度到额：停止新移动加速连接，已有连接自然结束。移动总额度到额：全部改走 Wi-Fi，现有移动连接会中断并需重连。'])]);
        var settings = E('div', { 'class': 'cbi-section' }, [E('h3', {}, ['出口与无线设置']),
            row('上网模式', mode, '分流模式遵循 OpenClash 当前规则：DIRECT 使用 Wi-Fi，代理节点使用移动数据。'),
            row('自动故障转移', failover, '任一出口不可用时使用另一条；原出口连续检测恢复后自动回切。'),
            row('无线名称（SSID）', ssid), row('无线频段', band), row('无线加密', encryption), row('无线密码', key),
            row('网络扫描', E('div', {}, [scanButton, scanResult])),
            E('p', {}, ['保存只记录设置；应用后才修改当前网络。'])]);
        var saveSettings = function() { return api.configure(mode.value, ssid.value, encryption.value, key.value, String(failover.checked), band.value, String(boostEnabled.checked), 'round-robin', boostDevices.value, boostDomains.value, dailyLimit.mib(), monthlyLimit.mib(), String(billingDay.value), mobileDaily.mib(), mobileMonthly.mib(), deviceMode.value).then(function(r) { if (r.ok) key.value = '';notify(r); }); };
        function actions() { return E('div', { style: 'margin:12px 0' }, [button('保存设置', saveSettings, true), button('应用已保存设置', function() { return api.apply().then(notify); }, false)]); }
        quotaPanel.appendChild(actions());
        accelerationPanel.appendChild(actions());
        settings.appendChild(actions());

        var noticeText = '请关闭 F50 发出的 Wi-Fi 热点，使用有线连接。保留 F50 连接其他 Wi-Fi 的功能，不要关闭整个 Wi-Fi。';
        var noticeKey = 'wifi-data-switch-f50-notice-v1';
        var acknowledged = false;
        try { acknowledged = localStorage.getItem(noticeKey) === 'yes'; } catch (_) {}
        if (!acknowledged && ui.showModal) {
            ui.showModal('使用前请确认', [E('p', {}, ['本插件为 F50 设计，目前仅在 F50 上测试。其他设备暂未验证。']), E('p', {}, [noticeText]),
                button('我已确认，继续使用', function() { try { localStorage.setItem(noticeKey, 'yes'); } catch (_) {} ui.hideModal(); }, true)]);
        }
        return E('div', {}, [E('style', {}, ['.wds-device-picker{margin-top:12px;border:1px solid var(--border-color,#d8dfe5);border-radius:10px}.wds-device-summary{padding:14px;cursor:pointer;line-height:1.7}.wds-devices-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,245px),1fr));gap:10px}.wds-device-card{display:flex;gap:12px;align-items:flex-start;padding:14px;border:1px solid var(--border-color,#d8dfe5);border-radius:9px;cursor:pointer;line-height:1.55}.wds-device-card input{margin-top:5px;flex-shrink:0;accent-color:#258a78}.wds-device-selected{border-color:#258a78;background:rgba(37,138,120,.07)}.wds-device-name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wds-device-ip{font-family:monospace;margin-top:3px}.wds-device-state{font-size:12px;margin-top:8px;opacity:.7}.wds-device-recent{color:#258a78;opacity:1}.wds-device-card:focus-within{outline:2px solid #258a78;outline-offset:2px}']), E('h2', {}, ['Wi-Fi / 数据切换']),
            E('p', {}, ['为 F50 设计的 Wi-Fi 与移动数据分流工具，目前仅在 F50 上测试。']),
            E('details', {}, [E('summary', {}, ['使用前须知']), E('p', {}, [noticeText]), E('p', {}, ['其他设备暂未验证，请勿直接套用配置。'])]), cards,
            E('div', { 'class': 'cbi-section', 'style': 'padding:16px' }, [summary]), usagePanel, accelerationPanel, quotaPanel, settings]);
    }
});
