'use strict';
'require view';
'require rpc';
'require poll';
'require ui';

var api = {};
[['status', []], ['configure', ['mode', 'ssid', 'encryption', 'wifi_key', 'failover', 'band', 'boost_enabled', 'boost_strategy', 'boost_devices', 'boost_domains', 'daily_mib', 'monthly_mib', 'billing_day', 'mobile_daily_mib', 'mobile_monthly_mib', 'boost_device_mode', 'boost_scope']],
 ['scan', []], ['devices', []], ['apply', []]].forEach(function(entry) {
    api[entry[0]] = rpc.declare({ object: 'wifi-data-switch', method: entry[0], params: entry[1], expect: {} });
});
function notify(result) {
    ui.addNotification(null, E('p', {}, [result.message || (result.ok ? '已完成' : '操作失败')]), result.ok ? 'info' : 'warning');
}
function row(label, input, help) {
    return E('div', { 'class': 'wds-field' }, [E('div', { 'class': 'wds-label' }, [label]),
        E('div', { 'class': 'wds-control' }, help ? [input, E('div', { 'class': 'wds-help' }, [help])] : [input])]);
}
function button(text, action, primary) {
    var b = E('button', { type: 'button', 'class': 'cbi-button ' + (primary ? 'cbi-button-apply' : 'cbi-button-action'), click: function() {
        b.disabled = true;
        return Promise.resolve().then(action).catch(function() { notify({ok:false, message:'操作失败，请重试。'}); }).finally(function() { b.disabled = false; });
    } }, [text]);
    return b;
}
function toggle(input, text) { return E('label', { 'class':'wds-toggle' }, [input, E('span', {}, [text])]); }
function panel(title, children) { return E('section', { 'class':'wds-panel' }, [E('h3', {}, [title])].concat(children)); }
return view.extend({
    handleSaveApply: null, handleSave: null, handleReset: null,
    load: function() { return api.status(); },
    render: function(initial) {
        var cfg = initial.settings || {};
        var modes = { split:'OpenClash 分流', wifi:'全部走 Wi-Fi', mobile:'全部走移动数据', direct:'仅双网加速（无代理）' };
        var routeLabel = function(v) { return v === 'none' ? '已停用' : (v === 'wifi' ? 'Wi-Fi' : '移动数据'); };
        var cards = E('div', { 'class':'wds-status-grid' });
        var summary = E('div', { 'class':'wds-summary' });
        var usagePanel = E('div', { 'class':'wds-usage' });
        var pending = E('span', { 'class':'wds-save-state' });
        var lastCounters = {};
        function card(title, info, health, detail) {
            var now = Date.now(), prev = lastCounters[title], c = info.counters || {};
            lastCounters[title] = {time:now, tx:c.tx_bytes, rx:c.rx_bytes};
            var rate = function(key) { return prev && c[key] != null && prev[key === 'tx_bytes' ? 'tx' : 'rx'] != null && now > prev.time ? (Math.max(0, c[key] - prev[key === 'tx_bytes' ? 'tx' : 'rx']) * 8 / ((now - prev.time) * 1000)).toFixed(2) : '—'; };
            return E('div', { 'class':'wds-link' }, [E('div', { 'class':'wds-link-head' }, [E('h3', {}, [title]), E('span', {'class':'wds-badge' + (health.online ? ' wds-good' : '')}, [health.online ? '已联网' : info.up ? '待认证 / 检测中' : '未连接'])]),
                E('div', { 'class':'wds-link-detail' }, [detail || '—']),
                E('div', { 'class':'wds-rate' }, [E('strong', {}, [rate('rx_bytes')]), E('span', {}, ['Mbps 下载']), E('span', {'class':'wds-up'}, ['↑ ' + rate('tx_bytes') + ' Mbps'])]),
                E('div', { 'class':'wds-link-detail' }, [(info.addresses || []).join(', ') || '—'])]);
        }
        function update(s) {
            var w = s.wifi || {}, m = s.mobile || {}, h = s.health || {};
            cards.replaceChildren(card('Wi-Fi', w, h.wifi || {}, (w.ssid || (s.settings || {}).ssid || '') + (w.signal ? ' · ' + w.signal + ' dBm' : '')), card('移动数据', m, h.mobile || {}, m.up ? '蜂窝已连接' : '等待蜂窝连接'));
            var usage = s.usage || {}, networks = usage.networks || {}, daily = usage.daily || {}, monthly = usage.monthly || {};
            function amount(v) { v = Number(v || 0); return v >= 1073741824 ? (v / 1073741824).toFixed(2) + ' GiB' : (v / 1048576).toFixed(1) + ' MiB'; }
            function budget(v) { return amount(v.used) + (v.limit ? ' / ' + amount(v.limit) : ''); }
            function usageRow(name, d, mo) { return E('tr', {}, [E('th', {}, [name]), E('td', {}, [budget(d || {})]), E('td', {}, [budget(mo || {})])]); }
            usagePanel.replaceChildren(E('table', {}, [E('thead', {}, [E('tr', {}, [E('th', {}, ['流量用量']), E('th', {}, ['今日']), E('th', {}, ['本月周期'])])]), E('tbody', {}, [usageRow('Wi-Fi 总用量', (networks.wifi || {}).daily, (networks.wifi || {}).monthly), usageRow('移动总用量', (networks.mobile || {}).daily, (networks.mobile || {}).monthly), usageRow('其中：加速移动流量', daily, monthly)])]));
            var savedMode = s.mode || (s.settings || {}).mode, boost = s.boost || {};
            var normalProxy = savedMode === 'direct' ? 'none' : savedMode === 'wifi' ? 'wifi' : 'mobile';
            var fallback = s.ready && (s.direct !== (savedMode === 'mobile' ? 'mobile' : 'wifi') || s.proxy !== normalProxy);
            var message = !s.ready ? '服务未运行' : (s.last_error || {}).error_type ? '网络检测异常' : s.quota_wifi_only ? '移动流量已到额，当前仅使用 Wi-Fi' : fallback ? '正在使用备用网络' : '网络正常';
            var boostText = boost.active && s.clash_bound ? '运行中 · ' + (boost.scope === 'domains' ? '指定域名' : '全部直连 TCP') : boost.reason || '已关闭';
            var alert = E('div', {'class':'wds-alert'}, [!usage.ready ? '流量统计未就绪，加速暂停' : usage.mobile_total_exceeded ? '移动总量已到额' : '加速流量已到额']); alert.hidden = !usage.exceeded && usage.ready !== false;
            summary.replaceChildren(E('div', {'class':'wds-summary-head'}, [E('strong', {}, [modes[savedMode] || '读取中']), E('span', {'class':'wds-muted'}, [message])]),
                E('div', {'class':'wds-routes'}, [E('span', {}, ['直连 → ' + routeLabel(s.direct)]), E('span', {}, ['代理 → ' + routeLabel(s.proxy)])]),
                E('div', {'class':'wds-boost-status'}, ['双网加速：' + boostText]),
                alert);
            pending.replaceChildren(s.pending ? '已保存，待应用' : '设置已应用');
        }
        update(initial);
        poll.add(function() { return api.status().then(update); }, 5);

        var mode = {value:cfg.mode || 'split'}, modeInputs = [];
        var modeOptions = E('div', {'class':'wds-mode-grid'}, Object.keys(modes).map(function(k) {
            var radio = E('input', {type:'radio', name:'wds-mode', value:k}); radio.checked = mode.value === k; modeInputs.push(radio);
            radio.addEventListener('change', function() { if (radio.checked) mode.value = k; });
            var hint = {split:'直连用 Wi-Fi，代理用移动数据', wifi:'直连和代理均使用 Wi-Fi', mobile:'直连和代理均使用移动数据', direct:'停止代理，直接使用两条网络'}[k];
            return E('label', {'class':'wds-mode-card'}, [radio, E('span', {}, [E('strong', {}, [modes[k]]), E('span', {'class':'wds-mode-hint'}, [hint])])]);
        }));
        var ssid = E('input', {'class':'cbi-input-text', type:'text', value:cfg.ssid || '', maxlength:'32'});
        var encryption = E('select', {'class':'cbi-input-select'}, [['none','开放网络'], ['psk2','WPA2'], ['sae','WPA3'], ['sae-mixed','WPA2 / WPA3']].map(function(v) { return E('option', {value:v[0]}, [v[1]]); })); encryption.value = cfg.encryption || 'none';
        var band = E('select', {'class':'cbi-input-select'}, [E('option', {value:'5g'}, ['5 GHz']), E('option', {value:'2g'}, ['2.4 GHz'])]); band.value = cfg.band || '5g';
        var key = E('input', {'class':'cbi-input-password', type:'password', autocomplete:'new-password', placeholder:'留空保留原密码'});
        var failover = E('input', {type:'checkbox'}); failover.checked = cfg.failover !== false;
        var scanResult = E('div', {'class':'wds-scan-results'});
        var scanButton = button('扫描 Wi-Fi', function() { return api.scan().then(function(r) {
            var seen = {}, entries = (r.results || []).filter(function(v) { if (!v.ssid || seen[v.ssid]) return false; seen[v.ssid] = true; return true; });
            scanResult.replaceChildren.apply(scanResult, entries.length ? entries.map(function(v) { return button(v.ssid + (v.signal == null ? '' : ' · ' + v.signal + ' dBm'), function() {
                ssid.value = v.ssid; encryption.value = v.encryption && v.encryption.enabled ? 'psk2' : 'none'; band.value = Number(v.frequency) > 4000 ? '5g' : '2g';
            }, false); }) : [E('p', {}, ['未发现网络'])]);
        }); }, false);
        var boostEnabled = E('input', {type:'checkbox'}); boostEnabled.checked = !!cfg.boost_enabled;
        var boostScope = E('select', {'class':'cbi-input-select'}, [E('option', {value:'all_tcp'}, ['全部直连 TCP']), E('option', {value:'domains'}, ['仅指定域名'])]); boostScope.value = cfg.boost_scope || 'all_tcp';
        var boostDevices = E('textarea', {'class':'cbi-input-textarea', rows:'3', placeholder:'每行一个 IP 或网段'}, [cfg.boost_devices || '']); boostDevices.value = cfg.boost_devices || '';
        var recommendedDomains = (initial.recommended_domains || ['download.windowsupdate.com', 'dl.delivery.mp.microsoft.com', 'mirrors.tuna.tsinghua.edu.cn', 'mirrors.ustc.edu.cn']).join('\n');
        var boostDomains = E('textarea', {'class':'cbi-input-textarea', rows:'7', placeholder:'每行一个域名，包含子域名'}, [cfg.boost_domains || recommendedDomains]); boostDomains.value = cfg.boost_domains || recommendedDomains;
        var deviceMode = E('select', {'class':'cbi-input-select'}, [E('option', {value:'all'}, ['全部设备']), E('option', {value:'whitelist'}, ['仅选中设备 · 白名单']), E('option', {value:'blacklist'}, ['排除选中设备 · 黑名单'])]); deviceMode.value = cfg.boost_device_mode || (cfg.boost_devices ? 'whitelist' : 'all');
        var deviceList = E('div', {'class':'wds-devices-grid'}), inventory = [];
        var deviceSummary = E('summary', {'class':'wds-device-summary'});
        var devicePickerDetails;
        function renderDevices() {
            var selected = boostDevices.value.split(/[\s,]+/).filter(Boolean);
            deviceSummary.replaceChildren(E('strong', {}, ['选择设备']), E('span', {'class':'wds-muted'}, ['已选 ' + new Set(selected).size + ' 项 · ' + inventory.length + ' 台设备']));
            if (devicePickerDetails) devicePickerDetails.hidden = deviceMode.value === 'all';
            deviceList.replaceChildren.apply(deviceList, inventory.length ? inventory.map(function(d) {
                var check = E('input', {type:'checkbox'}); check.checked = selected.indexOf(d.ip) >= 0 || selected.indexOf(d.ip + '/32') >= 0;
                check.addEventListener('change', function() { var values = boostDevices.value.split(/[\s,]+/).filter(function(v) { return v && v !== d.ip && v !== d.ip + '/32'; }); if (check.checked) values.push(d.ip); boostDevices.value = values.join('\n'); renderDevices(); });
                return E('label', {'class':'wds-device-card' + (check.checked ? ' wds-device-selected' : '')}, [check, E('div', {}, [E('strong', {}, [d.name || '未命名设备']), E('div', {'class':'wds-device-ip'}, [d.ip]), E('span', {'class':'wds-muted'}, [d.state === 'recent' ? '最近在线' : d.state === 'lease' ? '租约记录' : '缓存记录'])])]);
            }) : [E('p', {}, ['暂无设备记录'])]);
        }
        function loadDevices() { return api.devices().then(function(r) { inventory = r.devices || []; renderDevices(); }); }
        deviceMode.addEventListener('change', renderDevices); boostDevices.addEventListener('change', renderDevices);
        devicePickerDetails = E('details', {'class':'wds-device-picker'}, [deviceSummary, E('div', {'class':'wds-device-body'}, [button('刷新设备', loadDevices, false), deviceList, E('details', {'class':'wds-details'}, [E('summary', {}, ['手动填写 IP / 网段']), boostDevices])])]); devicePickerDetails.hidden = deviceMode.value === 'all';
        loadDevices().catch(function() { deviceList.replaceChildren(E('p', {}, ['设备列表读取失败'])); });
        var devicePicker = E('div', {}, [deviceMode, devicePickerDetails]);
        var domainPicker = row('加速域名', E('div', {}, [boostDomains, button('恢复默认', function() { boostDomains.value = recommendedDomains; }, false)]), '填写下载或更新使用的域名，自动包含子域名。');
        function updateScope() { domainPicker.hidden = boostScope.value !== 'domains'; }
        boostScope.addEventListener('change', updateScope); updateScope();
        function quotaInput(saved) {
            var factor = 1024;
            var input = E('input', {'class':'cbi-input-text', type:'number', min:'0', step:'any', value:Number(saved || 0) / factor});
            var unit = E('select', {'class':'cbi-input-select'}, [E('option', {value:'1024'}, ['GiB']), E('option', {value:'1'}, ['MiB'])]); unit.value = '1024';
            unit.addEventListener('change', function() { var next = Number(unit.value); if (input.value !== '' && Number.isFinite(Number(input.value))) input.value = Number(input.value) * factor / next; factor = next; });
            return {widget:E('span', {'class':'wds-quota-input'}, [input, unit]), mib:function() { var value = Number(input.value) * factor; if (!Number.isFinite(value) || value < 0 || value > 100000000) throw new Error('额度超出范围'); return String(Math.round(value)); }};
        }
        var dailyLimit = quotaInput(cfg.daily_mib), monthlyLimit = quotaInput(cfg.monthly_mib), mobileDaily = quotaInput(cfg.mobile_daily_mib), mobileMonthly = quotaInput(cfg.mobile_monthly_mib);
        var billingDay = E('input', {'class':'cbi-input-text', type:'number', min:'1', max:'28', value:cfg.billing_day || 1});
        var accelerationPanel = panel('双网加速', [row('加速开关', toggle(boostEnabled, '开启双网加速'), '两条网络均可用时生效。'), row('流量范围', boostScope, '全部直连无需填写域名；指定域名只加速清单内的流量。'), row('设备范围', devicePicker, '白名单只加速所选设备；黑名单排除所选设备。'), domainPicker,
            E('details', {'class':'wds-details'}, [E('summary', {}, ['哪些流量会加速？']), E('p', {}, ['全部直连 TCP 包括普通下载和网页连接，不必逐个填写域名。多连接任务更容易提速。']), E('p', {}, ['UDP、内网和常用远程端口保持原出口。单个连接仍只走一条网络；部分网站可能在意出口 IP 变化，可用设备黑名单排除。'])])]);
        var quotaPanel = panel('流量限额', [E('p', {'class':'wds-muted'}, ['移动总量包含所有移动数据；加速用量只计算双网加速使用的部分。0 表示不限额。']), E('div', {'class':'wds-form-grid'}, [row('每日移动总量', mobileDaily.widget), row('每月移动总量', mobileMonthly.widget), row('每日加速用量', dailyLimit.widget), row('每月加速用量', monthlyLimit.widget), row('每月结算日', billingDay, '1–28 日，月额度按此日期结算。')]),
            E('div', {'class':'wds-quota-notes'}, [E('p', {}, [E('strong', {}, ['加速用量到额']), '　停止加速，其他流量按原模式运行']), E('p', {}, [E('strong', {}, ['移动总量到额']), '　停用移动数据；Wi-Fi 断网时不再回退'])])]);
        var settings = panel('网络设置', [row('上网模式', modeOptions, '前三种模式保留代理规则；无代理模式会停止 OpenClash。'), row('自动切换', toggle(failover, '网络断开时使用另一条'), '恢复后自动切回，已有连接可能需要重连。'), E('h4', {}, ['连接 Wi-Fi']), E('p', {'class':'wds-section-intro'}, ['设置用于上网的 Wi-Fi，修改后可能短暂断网。']), E('div', {'class':'wds-form-grid'}, [row('Wi-Fi 名称', ssid), row('频段', band), row('加密方式', encryption), row('密码', key)]), scanButton, scanResult]);
        var saveSettings = function() { return api.configure(mode.value, ssid.value, encryption.value, key.value, String(failover.checked), band.value, String(boostEnabled.checked), 'round-robin', boostDevices.value, boostDomains.value, dailyLimit.mib(), monthlyLimit.mib(), String(billingDay.value), mobileDaily.mib(), mobileMonthly.mib(), deviceMode.value, boostScope.value).then(function(r) { if (r.ok) { key.value = ''; pending.replaceChildren('已保存，待应用'); } notify(r); }); };
        var actions = E('div', {'class':'wds-actions'}, [pending, E('div', {}, [button('保存设置', saveSettings, false), button('应用已保存设置', function() { return api.apply().then(function(r) { notify(r); if (r.ok) pending.replaceChildren('正在应用…'); }); }, true)])]);
        var overview = E('div', {}, [cards, panel('当前网络', [summary]), panel('流量用量', [E('p', {'class':'wds-section-intro'}, ['加速用量已包含在移动总量中。']), usagePanel, E('details', {'class':'wds-details'}, [E('summary', {}, ['统计说明']), E('p', {}, ['用量由路由器统计，可能与运营商账单有差异。']), E('p', {}, ['从启用统计后开始累计，之前的用量不计入。约每分钟保存一次，断电可能丢失最后一分钟的记录。'])])])]);
        var tabs = [], sections = [overview, settings, accelerationPanel, quotaPanel];
        var navigation = E('nav', {'class':'wds-tabs', 'aria-label':'页面分区'}, ['概览', '网络设置', '双网加速', '流量限额'].map(function(label, index) {
            var tab = button(label, function() { sections.forEach(function(s, i) { s.hidden = i !== index; }); tabs.forEach(function(t, i) { t.className = 'wds-tab' + (i === index ? ' wds-tab-active' : ''); }); }, false); tab.className = 'wds-tab' + (index === 0 ? ' wds-tab-active' : ''); tabs.push(tab); return tab;
        })); sections.forEach(function(s, i) { s.hidden = i !== 0; });
        var noticeText = '请关闭 F50 的 Wi-Fi 热点，保留连接其他 Wi-Fi 的功能。管理设备请使用有线连接。';
        var noticeKey = 'wifi-data-switch-f50-notice-v1', acknowledged = false;
        try { acknowledged = localStorage.getItem(noticeKey) === 'yes'; } catch (_) {}
        if (!acknowledged && ui.showModal) ui.showModal('使用前确认', [E('p', {}, ['目前仅在 F50 上测试。']), E('p', {}, [noticeText]), button('知道了', function() { try { localStorage.setItem(noticeKey, 'yes'); } catch (_) {} ui.hideModal(); }, true)]);
        return E('div', {'class':'wds-app'}, [E('link', {rel:'stylesheet', href:L.resource('view/wifi-data-switch/settings.css') + '?v=072-help'}), E('div', {'class':'wds-header'}, [E('h2', {}, ['Wi-Fi / 数据切换']), E('span', {'class':'wds-muted'}, ['F50'])]), navigation,
            E('div', {'class':'wds-content'}, [overview, settings, accelerationPanel, quotaPanel]), E('details', {'class':'wds-details wds-notice'}, [E('summary', {}, ['使用须知']), E('p', {}, [noticeText])]), actions]);
    }
});
