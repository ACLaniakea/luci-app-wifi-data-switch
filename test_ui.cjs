const fs = require('fs');
const assert = require('node:assert/strict');
const path = require('path');
class Element {
  constructor(tag, attrs, children) { this.tag = tag; this.attrs = attrs || {}; this.children = children || []; this.value = this.attrs.value || ''; }
  addEventListener(name, fn) { this.attrs[name] = fn; }
  replaceChildren(...nodes) { this.children = nodes; }
  appendChild(node) { this.children.push(node); }
}
function E(tag, attrs, children) { return new Element(tag, attrs, children); }
function walk(node) { return node instanceof Element ? [node, ...node.children.flatMap(walk)] : []; }
function text(node) { return node instanceof Element ? node.children.map(text).join(' ') : String(node); }
const state = { ready: true, mode: 'split', direct: 'wifi', proxy: 'mobile', clash_bound: true,
  health: { wifi: { online: true }, mobile: { online: true } },
  settings: { mode: 'split', ssid: 'Example-WiFi', encryption: 'none', failover: true },
  wifi: { up: true, addresses: ['192.0.2.2'], signal: '-55', frequency: '5220', counters: {} },
  mobile: { up: true, device: 'sipa_eth0', addresses: ['198.51.100.2'], counters: {} } };
const calls = [], polls = [];
const rpc = { declare(spec) { return (...args) => { calls.push([spec.method, args]); return Promise.resolve(spec.method === 'status' ? state : { ok: true, message: 'ok' }); }; } };
const source = fs.readFileSync(path.join(__dirname, 'files/www/luci-static/resources/view/wifi-data-switch/settings.js'), 'utf8');
const page = new Function('view', 'rpc', 'poll', 'ui', 'E', source)({ extend(v) { return v; } }, rpc,
  { add(fn) { polls.push(fn); } }, { addNotification() {} }, E);
async function test() {
  const dom = page.render(state);
  assert.match(text(dom), /直连 → Wi-Fi/);
  assert.match(text(dom), /OpenClash 代理 → 移动数据/);
  assert.match(text(dom), /全部走 Wi-Fi/);
  assert.match(text(dom), /全部走移动数据/);
  assert.match(text(dom), /加速移动流量/);
  assert.match(text(dom), /日/);
  assert.equal(polls.length, 1);
  const quotaWidget = walk(dom).find(v => v.tag === 'span' && v.children.length === 2 && v.children[1].tag === 'select' && v.children[1].value === '1024');
  quotaWidget.children[0].value = '1.5';
  quotaWidget.children[1].value = '1'; quotaWidget.children[1].attrs.change();
  assert.equal(Number(quotaWidget.children[0].value), 1536);
  quotaWidget.children[1].value = '1024'; quotaWidget.children[1].attrs.change();
  assert.equal(Number(quotaWidget.children[0].value), 1.5);
  const save = walk(dom).find(v => v.tag === 'button' && text(v) === '保存设置');
  await save.attrs.click();
  const config = calls.find(v => v[0] === 'configure');
  assert.equal(config[1][0], 'split');
  assert.equal(config[1][10], '1536');
  assert.equal(config[1][4], 'true');
  assert.equal(config[1][5], '5g');
  assert.equal(calls.some(v => /auth/.test(v[0])), false);
  assert.equal(save.disabled, false);
  state.direct = 'mobile'; state.health.wifi.online = false;
  await polls[0]();
  assert.match(text(dom), /直连 → 移动数据/);
  assert.match(text(dom), /待认证或联网检测中/);
  console.log('UI rendering, settings submission and live failover status passed.');
}
test().catch(error => { console.error(error); process.exitCode = 1; });
