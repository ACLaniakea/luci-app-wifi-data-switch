# Wi-Fi / 数据切换

为 F50 设计的 OpenWrt LuCI 插件（目前仅在 F50 上测试）：让 **OpenClash 的 DIRECT 流量走 Wi-Fi，代理节点走移动数据**，并提供双向故障切换、手动出口选择和实时状态页面。

Wi-Fi/cellular uplink selection and failover for OpenWrt, with OpenClash integration. **Experimental; originally developed and tested on F50 / MU300.**

## 状态与适用范围

当前 `0.4.0` 是从实际使用版本整理的实验性源码。原始版本在 F50 / MU300、OpenWrt 25.12 系列上验证过；本公开版本删除了专用网络认证与部署配置，增加了接口参数文件。公开版本的这些调整经过自动化测试，尚未重新在实体路由器部署验证。其他硬件尚未验证，不是任意 OpenWrt 设备即装即用的通用成品。

**不包含门户自动登录、校园账号保存或登录报文重放。** 需要网页认证的 Wi-Fi 请自行通过浏览器完成认证；插件只检测联网状态。

## 功能

| 模式 | DIRECT 出口 | OpenClash 代理节点出口 |
| --- | --- | --- |
| OpenClash 分流 | Wi-Fi | 移动数据 |
| 全部走 Wi-Fi | Wi-Fi | Wi-Fi |
| 全部走移动数据 | 移动数据 | 移动数据 |

“全部走某出口”表示改变代理节点连接外网使用的底层网络，保留 OpenClash 原有代理规则，并不关闭代理。这里的代理流量由 OpenClash 的规则决定，不是按地理位置自动识别所有境外流量。

- 自动故障转移：任一出口故障时使用另一出口，恢复后自动回切；可以关闭。
- 连续 3 轮失败确认故障、连续 2 轮成功确认恢复，接口断开立即标记不可用。
- 上联 Wi-Fi 扫描、SSID、频段、WPA2/WPA3 密码设置。
- 两条出口的联网状态、地址、Wi-Fi 信号、接口总上传/下载速率、实际出口和最近切换时间。
- 自定义出口切换后要重启的服务列表，默认不重启任何其他服务。

检测周期通常为十几秒，全部探测超时时会更长；不承诺秒级切换或已有连接不断。两条网络同时故障时无法提供联网。

## 工作方式

Wi-Fi 使用已有 STA 无线 WAN + NAT，属于路由模式，不是四地址透明桥接。插件不创建 WAN、LAN、DHCP 或防火墙区域，不接管蜂窝拨号。

控制器基于 ubus 的接口信息和绑定具体接口的 HTTP 204 探测选择出口；策略路由选择 DIRECT 出口，给 Mihomo 代理节点和 proxy-provider override 设置 `interface-name`、`routing-mark`、IPv4 拨号，并通过本机控制接口重载配置。OpenClash 自定义覆写钩子在配置重新生成时保留绑定。

实现保留了以下固定资源：

| 资源 | 用途 |
| --- | --- |
| IPv4 路由表 201 / 202 | 移动数据 / Wi-Fi |
| fwmark `0x5751` / `0x5752` | 代理节点出口 |
| rule 优先级 10510、10511、10512、10520、10521、31020 | 出口选择 |
| nftables 表 `inet wifi_data_switch` | Wi-Fi DIRECT 模式下阻止 LAN IPv6 绕过至移动出口 |

这些资源必须未被其他服务占用。不建议与 mwan3、mwan4、pbr 等策略控制器同时管理相同流量。LAN IPv4 网段从配置的 LAN 逻辑接口获取；其他本地网段、VPN、容器网络需要另行评估绕过策略。

## 安装前提

1. 两条 IPv4 上联已经配置好，蜂窝为主路由默认出口；Wi-Fi 已加入 WAN 防火墙区域，具有 NAT 和 LAN 转发权限。
2. OpenClash / Mihomo 已运行，进程名为 `clash`，启动参数包含 `-f` 配置文件；核心位于 `/etc/openclash/clash`。适配的是 OpenClash TPROXY 常见布局，TUN 和其他透明代理布局尚未验证。
3. Wi-Fi 使用专用上联 radio；页面修改频段会重载该 radio。若它同时承载客户端 AP，客户端可能断网。
4. 安装 Python 3（3.9+）、Ruby、Ruby YAML/JSON、curl、CA 证书、iw、ip-full、nftables，以及 LuCI / rpcd 和 iwinfo 扫描支持。包名以固件仓库为准：`python3 ruby ruby-yaml ruby-json curl ca-bundle iw ip-full nftables rpcd-mod-iwinfo luci-base`。

## 从源码安装

在路由器上下载或上传本仓库，安装上述依赖，然后在源码根目录执行：

```sh
python3 install.py
```

安装器备份网络配置、原 OpenClash 自定义覆写钩子和被覆盖的插件文件到 `/root/wifi-data-switch-backups/时间戳/`；复制 LuCI 和后端文件，安装独立标记的 OpenClash 钩子。它不会启用或启动监测服务，也不会创建网络接口或修改 LAN 地址。新装初始模式为移动数据。

备份可能含 Wi-Fi 密码或订阅信息，请只留在自己设备上。

### 核对接口

示例采用最初 F50 的接口布局。其他设备请先查看 `ubus call network.interface.wan status`、`ubus call network.interface.wwan status`、`uci show wireless` 的实际值，再创建参数文件：

```sh
mkdir -p /etc/wifi-data-switch
chmod 700 /etc/wifi-data-switch
cp examples/hardware.json /etc/wifi-data-switch/hardware.json
chmod 600 /etc/wifi-data-switch/hardware.json
```

编辑 `/etc/wifi-data-switch/hardware.json`：

| 字段 | 示例 | 含义 |
| --- | --- | --- |
| `wifi_network` / `mobile_network` / `lan_network` | `wwan` / `wan` / `lan` | netifd 逻辑接口 |
| `wifi_device` / `mobile_device` / `lan_device` | `wlan-sta` / `sipa_eth0` / `br-lan` | 实际设备名；须与逻辑接口一致 |
| `radio` / `station` | `radio0` / `uplink` | `/etc/config/wireless` 中的 radio 和 STA section 名 |
| `clash_mark` | `0x162` | 现有 OpenClash TPROXY 标记 |
| `restart_services` | `[]` | DIRECT 出口变化后重启的已启用 init 服务名；默认空 |

参数修改后需重启本插件。接口参数目前通过文件设置，前端配置向导留待后续完善。

确认原蜂窝出口和 OpenClash 正常、参数无误后启用：

```sh
/etc/init.d/wifi-data-switch enable
/etc/init.d/wifi-data-switch start
```

刷新 LuCI，进入 **网络 → Wi-Fi / 数据切换**。首次先观察移动数据状态，再选择分流模式。页面地址路径为 `/cgi-bin/luci/admin/network/wifi-data-switch`。

### OpenWrt SDK 包配方

仓库提供 `Makefile`。可将本目录放入匹配版本的 OpenWrt SDK `package/luci-app-wifi-data-switch`，选择包并编译：

```sh
make menuconfig
make package/luci-app-wifi-data-switch/compile V=s
```

使用 SDK 生成的包安装后，还需要手动执行：

```sh
python3 /usr/libexec/wifi-data-switch/maintenance.py setup
```

然后按上面的接口检查与启用步骤操作。当前没有提供或验证预编译的 `.ipk` / `.apk`，也不包含固件镜像。

## 停用、卸载和回退

只想临时停用时，先在页面切换“全部走移动数据”，等代理绑定生效，然后停止并禁用服务：

```sh
/etc/init.d/wifi-data-switch stop
/etc/init.d/wifi-data-switch disable
```

临时停止会撤下 Wi-Fi DIRECT 策略与 IPv6 保护，保留代理的当前绑定和显式出口路由，方便已建立连接继续工作。它不等于完整卸载。

完整清理前，准备好未被插件绑定的 OpenClash 订阅配置或备份；清理和重新加载会使部分连接中断：

```sh
python3 /usr/libexec/wifi-data-switch/maintenance.py cleanup
```

该命令停止并禁用服务，移除本插件的覆写钩子、上述规则、路由表和 IPv6 保护表。**它不会自动回写旧订阅配置**，以免覆盖你的后续修改。此时重新获取原始订阅/导入原配置，再重启 OpenClash，使 `interface-name`、`routing-mark` 和 `ip-version` 恢复原设定；首次绑定前的配置备份在 `/etc/wifi-data-switch/clash-before-binding.yaml`，仅在确认它仍适用时手动恢复。

通过包管理器安装的版本，清理后使用原包管理器删除 `luci-app-wifi-data-switch`。源码安装的版本可删除以下插件专属路径：

```sh
rm -f /etc/init.d/wifi-data-switch /usr/libexec/rpcd/wifi-data-switch
rm -f /usr/share/rpcd/acl.d/luci-app-wifi-data-switch.json
rm -f /usr/share/luci/menu.d/luci-app-wifi-data-switch.json
rm -rf /www/luci-static/resources/view/wifi-data-switch
rm -rf /usr/libexec/wifi-data-switch /var/run/wifi-data-switch
/etc/init.d/rpcd reload
```

`/etc/wifi-data-switch` 和 `/root/wifi-data-switch-backups` 默认保留，核对无需保留后再自行删除。无需恢复整个网络配置来卸载本插件。

## 验证与已知限制

```sh
python3 -m unittest discover -p 'test_*.py'
node test_ui.cjs
```

测试覆盖模式选择、健康阈值、LAN 绕过生成、RPC 认证功能移除、钩子安装/清理、UI 提交与状态刷新。CI 还执行 Python/Ruby/JS/shell 语法与 JSON 检查。它们不替代实体网络故障切换测试。

- 原始部署验证过两条出口和三种模式，并模拟健康结果验证了实际路由、Clash 重载与备用出口；未物理断网测试所有硬件。
- IPv4 优先，不提供完整双出口 IPv6 策略。Wi-Fi DIRECT 模式会阻止 LAN IPv6 直接走蜂窝。
- HTTP 204 探测判断的是探测端点可达性，不能证明所有网站、DNS 和代理节点都正常。
- 代理绑定失败时保留移动默认出口，页面显示未就绪；不是严格的“只准某出口”防泄漏工具。
- 自动故障转移、NAT 和上游地址变化可能让串流、下载或远程连接重建。
- 不支持任意设备的首次联网自动配置，不和其他策略路由插件争抢相同规则。

## 后续计划

- 改善手机页面、状态展示和错误提示。
- 提供接口选择、首次配置和更完整的回退向导。
- 增加设备与固件兼容性测试。
- 完善连接保持、探测策略和诊断信息。

## 相似项目

[Travelmate](https://github.com/openwrt/packages/tree/master/net/travelmate) 管理 Wi-Fi 上联；[mwan3](https://openwrt.org/docs/guide-user/network/wan/multiwan/mwan3) 管理多 WAN；[pbr](https://docs.mossdef.org/pbr/) 提供策略路由。本项目侧重将 OpenClash 代理与 DIRECT 的双出口选择整合成一个小型 LuCI 页面。

## License

MIT，详见 [LICENSE](LICENSE)。本仓库不包含 OpenClash/Mihomo，其代码与许可证由各自项目维护。

## 0.2.0：指定范围的直连双网加速

在分流模式下开启「直连双网加速」，填写设备 IPv4/网段或域名。0.5.0 起设备范围与域名同时匹配才加速，设备模式默认为全部设备。两条出口必须同时通过健康检测，否则恢复原来的单出口与故障转移。

仅将原配置中明确以 DIRECT 为目标的简单规则接入范围子规则，保留规则顺序和代理目标。手动选择 DIRECT 的代理组、复杂逻辑规则和未经过 Mihomo 的绕行流量不在首版支持范围内。只加速 TCP；UDP、私网、SSH、RDP、Sunshine 和 RustDesk 常用端口保留原出口。自定义远程端口不保证自动识别，勿把相关设备整体纳入吞吐优先。

稳定优先使用 sticky-sessions，同设备同站点尽量保持出口；吞吐优先使用 round-robin，分配新连接。两者都不是单连接带宽叠加，也不是按字节均分。不同公网 IP 可能影响登录会话，因此默认关闭、范围不可为空。

加速入口在现有设置页面，展示运行中/等待条件/关闭状态。改变范围、健康状态或出口会触发配置验证与重载，可能影响已有会话。禁用会移除生成的专用节点、策略组及子规则，恢复原规则。数据额度、按字节权重和代理带宽预留尚未实现，开启后会额外消耗移动数据；不能作为运营商流量计费控制工具。

## 0.3.0：加速移动流量额度与页面分区

页面将联网状态、加速范围、额度设置及无线设置分开显示。额度输入支持 GiB / MiB 分别切换，默认 GiB，支持小数；1 GiB=1024 MiB，后台按最接近的整数 MiB 保存。0 表示不限额。用量自动以 GiB 或 MiB 展示。可配置每日额度、月额度与 1–28 日的结算日，任一额度达到后不再为新加速连接分配移动出口。已有连接自然结束，不强制断开，可能继续消耗流量。该版本不含立即终止连接选项。

加速专用移动直连节点使用独立 fwmark `0x5753`（rule 10513 → table 201）；nftables `inet wds_meter` 在 OUTPUT 将其 conntrack mark 的 `0x40000000` 位标记，统计出站 IPv4 包和 PREROUTING 中对应 reply 包的长度。此位和上述表/规则须未被其他服务占用；其他代理节点仍用原标记，不计入加速额度。计数包含 IP/TCP/TLS 开销和该节点健康探测，与应用文件字节数或运营商计费可能不同。

计量无需轮询 Clash 的在途连接列表，因此不会因为短连接在两次轮询间结束而漏记整个连接。每轮健康检测更新额度；约每分钟原子保存 `/etc/wifi-data-switch/usage.json`，正常退出也保存。runtime 快照在 `/var/run/wifi-data-switch/usage-status.json`。计数器重置和 boot_id 变化按新基线累计，按天保存历史，以便变更结算日重算月度用量。设备时钟需正确，跨日附近的流量以采样时间归属。

突然断电可能丢失最近未持久化的用量；控制周期与已有连接使额度不是严格账单上限。统计器异常时暂停新双网加速，页面展示原因，原单网分流继续。临时停用保留计量表以计入还未结束的加速连接；maintenance cleanup 会清理专用规则和计量表。统计清零/手动修订暂不提供 UI。

已在 F50 使用独立临时核心和四条 HTTPS Range 下载连接验证专用移动标记、上下行计数及普通移动代理标记隔离的设计；Python 测试覆盖增量、计数重置、持久化续计、额度与结算日重算。生产加速默认仍关闭，没有替用户选择下载域名或开启不受限移动加速。

## 首次使用与设置生效

首次打开页面会提示关闭 F50 发出的无线热点、使用有线连接，并保留其连接其他 Wi-Fi 的能力；确认记录保存在当前浏览器，页面「使用前须知」可随时查看。本插件目前仅在 F50 上测试，其他设备暂未验证，不应把参数可配置理解为通用适配。

每个设置区提供「保存设置」与「应用已保存设置」：保存仅在设备上写入受限权限的待应用配置，刷新页面仍保留，后台继续使用原有设置；点击应用后才修改网络并生效。无线密码不会通过状态接口返回。应用失败时保留待应用配置，便于修改后重试。

## 0.4.0：Wi-Fi 与移动数据总量

首页同时显示 Wi-Fi 总用量、移动数据总用量，以及独立的加速移动用量，每组都有今日和本计费周期统计。总量来自各出口设备的 rx_bytes + tx_bytes，包含代理、普通上网、加速及设备后台流量，覆盖 IPv4/IPv6；它与加速专用 IPv4 计数器的计量层级不同，不能简单相减得到准确的普通流量。

首次启用总量统计时以当前接口计数为基线，记录开始时间，不把启用前整次开机的流量归到今天，也无法恢复运营商本月历史账单。使用 shared billing_day；数据保存在 usage.json 内 networks 字段，按日累计，正常重启续计，接口计数或 boot_id 重置后使用新基线。持久化间隔和突然断电限制同加速计量。

可分别设置每日、每月移动总额度，单位支持 GiB / MiB，0 为不限额。达到任一总额度后，代理和直连全部改走 Wi-Fi，并通过 nftables 拦截移动接口的本机 OUTPUT 与转发 FORWARD 流量（IPv4/IPv6）。已有移动连接会被阻断、需经 Wi-Fi 重建；Wi-Fi 不可用时不允许回退移动出口。若统计从月中开始，所设额度只约束统计起点之后的流量，不能当作完整账期已用量。

F50 实测分别通过 wlan-sta 和 sipa_eth0 下载 1 MiB：两个总计数都增加，加速计数保持不变（测试时加速关闭）。后台同时有其他流量，接口增量不是纯测速文件大小。自动测试覆盖首次基线、接口更换、重启续计、总额度触发及 UI 提交。

## 0.4.1：两级额度策略

- 加速额度到额：停止双网加速的新移动连接，原代理出口策略不变；已有加速连接自然结束。
- 移动总额度到额：优先级高于手动模式和故障转移，代理与直连全部改走 Wi-Fi；`inet wds_mobile_limit` 拦截移动设备的 OUTPUT/FORWARD，防止既有移动 socket 和 IPv6 继续发送。Wi-Fi 故障时保持禁止移动回退。
- 周期重置或应用更高/不限额度后，下一轮计量会解除拦截，恢复所选模式。总量到额状态下重启/停止插件保留拦截与 Wi-Fi 策略，避免重启过程中绕过；完整 maintenance cleanup 会移除它们。额度统计中断时沿用此前已触发的总量限制。

该策略仍以路由器周期采样计数为依据，检测间隔内可能超额，也无法控制本插件外的蜂窝调制解调器自身流量。不是运营商账单硬保证。停止监测后不会自动解除已经触发的总额度，需要重新启动插件并应用额度设置，或执行 cleanup。

F50 测试：完整 IPv4/IPv6 guard 的 nft 语法检查通过；将同一规则限定到一个测试下载 IP 后，移动下载被阻断、Wi-Fi 成功，删除临时规则后移动恢复。该测试避免实际切断生产移动连接；模式优先级与 Wi-Fi 故障不回退由单元测试覆盖。

## 0.5.0：设备选择与推荐下载清单

设备范围支持「全部设备」（默认）、「仅选中设备／白名单」、「排除选中设备／黑名单」。列表默认折叠，标题显示模式、所选项数和设备记录数；展开后使用自适应卡片显示名称、IP、MAC 与最近通信/租约/缓存状态。可勾选或手动填写 IP/网段，未知或离线记录不自动删除已保存的选择。列表来自 F50 的 DHCP 租约和 LAN 邻居缓存，不主动扫描，不能保证设备此刻在线。按 IP 匹配，地址改变需刷新选择，长期固定策略建议静态租约。

设备范围和下载域名必须同时匹配，原 OpenClash 规则还必须明确选择 DIRECT。白名单中非所选设备不加速；黑名单排除先于域名匹配。旧版填写过 IP 而没有设备模式时按白名单展示。UDP、内网、远程端口保护不变。

域名框为空时显示推荐清单，可编辑；只有一个「恢复默认」按钮，替换表单为完整推荐清单，仍需保存并应用。已有非空清单不被覆盖。不会自动开启加速。默认包含 22 个下载端点，见 [推荐下载域名](examples/recommended-download-domains.txt)：Windows 更新、开源镜像、Steam、Epic、米哈游国服和国际服（原神、崩坏：星穹铁道、绝区零、崩坏3）。没有加入整个游戏平台、账号或支付父域名。

来源与边界：

- [Microsoft 更新端点](https://learn.microsoft.com/en-us/troubleshoot/windows-client/installing-updates-features-roles/windows-update-issues-troubleshooting) 支持更新下载端点。
- [Epic 官方网络端点](https://www.epicgames.com/help/c-36624475/c-35761596/which-domains-need-to-be-whitelisted-to-reach-the-epic-servers-a15422130?lang=en-US) 与 [LanCache 维护者的下载清单](https://github.com/uklans/cache-domains/blob/master/epicgames.txt) 支持 Epic 下载端点。
- Steam 的 steamcontent.com 下载用途由本机 Steam content_log 的内容服务器记录核对，不把整个 steampowered.com 纳入。
- 米哈游域名于 2026-11-16 从官方公开启动器接口 `hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1` 与 `sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api/getGamePackages?launcher_id=VYTpXlbWo8` 返回的资源 URL 核对。国际服资源若原规则走代理，仍走代理，不强制直连。
- 清华和中科大镜像用途见 [清华镜像站](https://mirrors.tuna.tsinghua.edu.cn/) 与 [中科大镜像说明](https://lug.ustc.edu.cn/wiki/lug/services/mirrors/)。

这些是下载用途推荐，不保证每个游戏、每个版本的多出口下载性能；新增 CDN 可能需要补充。下载器的连接数量及上下游瓶颈决定实际收益。
